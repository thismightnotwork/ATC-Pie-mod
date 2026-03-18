
#
# This file is part of the ATC-pie project,
# an air traffic control simulation program.
# 
# Copyright (C) 2015  Michael Filhol <mickybadia@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA
#

from sys import stderr
from os import path, remove
try:
	from pyaudio import PyAudio, paInt16
	from pocketsphinx import get_model_path
	from pocketsphinx import Decoder, Config
	speech_recognition_available = True
except ImportError:
	speech_recognition_available = False

from PyQt5.QtCore import QThread

from base.util import some
from base.instr import Instruction, ApproachType
from base.params import Heading, AltFlSpec, Speed
from base.db import phon_airlines, phon_navpoints, get_phonemes

from gui.misc import signals

from session.config import settings


# ---------- Constants ----------

log_speech_recognition = False # debug constant

src_lexicon_file = 'resources/speech-recog/instr.dict'
src_grammar_file = 'resources/speech-recog/instr.jsgf'

prepared_lexicon_file_base_name = 'sr-lexicon'
prepared_grammar_file_base_name = 'sr-grammar'
sphinx_decoder_log_file_base_name = 'sr-decoder'

message_duration_limit = 10 # s
audio_chunk_size = 1024
audio_sample_rate = 16000

airline_token_prefix = 'airline-'
navpoint_token_prefix = 'navpoint-'

# -------------------------------



def SR_log(*args):
	if log_speech_recognition:
		with open(settings.outputFileName('sr-debug', ext='log'), mode='a', encoding='utf8') as f:
			print('\t'.join(str(arg) for arg in args), file=f)





def prepare_SR_language_files():
	"""
	NOTE: To be called at every new location (for navpoint name update).
	"""
	settings.prepared_lexicon_file = settings.outputFileName(prepared_lexicon_file_base_name, ext='dict')
	settings.prepared_grammar_file = settings.outputFileName(prepared_grammar_file_base_name, ext='jsgf')
	with open(settings.prepared_lexicon_file, 'w', encoding='utf8') as lex_out:
		with open(settings.prepared_grammar_file, 'w', encoding='utf8') as gram_out:
			with open(src_lexicon_file, encoding='utf8') as lex_in:
				lex_out.write(lex_in.read())
			with open(src_grammar_file, encoding='utf8') as gram_in:
				gram_out.write(gram_in.read())
			gram_out.write('\n\n/*** APPENDED BY ATC-PIE ***/\n\n')
			for grammar_rule, token_prefix, pron_dict in [
					('airline_callsign', airline_token_prefix, phon_airlines),
					('named_navpoint', navpoint_token_prefix, phon_navpoints)
				]:
				gram_out.write('<%s> =' % grammar_rule)
				got_first = False
				for token in pron_dict:
					lex_out.write('\n%s%s  %s' % (token_prefix, token, get_phonemes(pron_dict, token)))
					gram_out.write('\n%s %s%s' % (('|' if got_first else ' '), token_prefix, token))
					got_first = True
				if got_first:
					gram_out.write('\n;\n\n')
				else:
					gram_out.write(' <NULL>;\n\n')


def cleanup_SR_language_files():
	for f in settings.prepared_lexicon_file, settings.prepared_grammar_file:
		if f is not None:
			try:
				remove(f) # os.remove
			except FileNotFoundError:
				print('WARNING: Could not delete temp file %s' % f, file=stderr)
	settings.prepared_lexicon_file = settings.prepared_grammar_file = None


# ---------------------------------------------------------------------------------------------------


class InstructionRecogniser(QThread):
	"""
	You should only use keyIn/keyOut, and shutdown after use. The thread starts itself when appropriate.
	Signals are emitted with any recognised instructions.
	"""
	def __init__(self, gui):
		QThread.__init__(self, gui)
		if settings.sphinx_acoustic_model_dir == '': # use default acoustic model
			acoustic_model_directory = path.join(get_model_path(), 'en-us')
		else: # use custom acoustic model
			acoustic_model_directory = settings.sphinx_acoustic_model_dir
		config = Config(jsgf=settings.prepared_grammar_file) # language model from explicit grammar
		config.set_string('-hmm', acoustic_model_directory) # acoustic model
		config.set_string('-dict', settings.prepared_lexicon_file) # lexicon pronunciation
		config.set_string('-logfn', settings.outputFileName(sphinx_decoder_log_file_base_name, ext='log'))
		self.listen = False
		self.decoder = Decoder(config)
		self.audio = None
	
	def startup(self):
		self.audio = PyAudio()
	
	def shutdown(self):
		self.listen = False
		self.wait()
		self.audio.terminate()
		self.audio = None
	
	def keyIn(self):
		if not self.isRunning():
			self.listen = True
			self.start()
	
	def keyOut(self):
		self.listen = False

	def listening(self):
		return self.listen

	def run_DEBUG(self):
		while self.listen:
			self.msleep(1)
		tokstr = input('MANUALLY ENTER voice token string: ')
		SR_log('MANUAL ENTRY: "%s"' % tokstr)
		signals.statusBarMsg.emit('VOICE (manual debug entry): "%s"' % tokstr)
		callsign_tokens, instr_lst = interpret_string(tokstr)
		signals.voiceMsgRecognised.emit(callsign_tokens, instr_lst)

	def run(self):
		audio_stream = self.audio.open(channels=1, format=paInt16, rate=audio_sample_rate,
										frames_per_buffer=audio_chunk_size, input=True)
		chunks = []
		msg_duration = 0
		buff = audio_stream.read(audio_chunk_size)
		while self.listen and len(buff) > 0 and msg_duration < message_duration_limit:
			chunks.append(buff)
			buff = audio_stream.read(audio_chunk_size)
			msg_duration += audio_chunk_size / audio_sample_rate
		audio_stream.close()
		audio_message = b''.join(chunks)

		self.decoder.start_utt() # STYLE catch failures here (e.g. grammar/lex files not found)
		self.decoder.process_raw(audio_message, False, True)
		self.decoder.end_utt()
		hyp = self.decoder.hyp()
		if hyp:
			SR_log('VOICE: "%s"' % hyp.hypstr)
			if settings.show_recognised_voice_strings:
				signals.statusBarMsg.emit('VOICE: "%s"' % hyp.hypstr)
			callsign_tokens, instr_lst = interpret_string(hyp.hypstr)
			signals.voiceMsgRecognised.emit(callsign_tokens, instr_lst)
		else:
			SR_log('VOICE: no hypothesis, message duration was %g s' % msg_duration)
			signals.voiceMsgNotRecognised.emit()




## ## ## ##    GRAMMAR STUFF    ## ## ## ##

def interpret_string(string):
	tokens = string.split()
	sfc_to_expect = ' '.join(pop_named_depldgsfc(tokens))
	# CAUTION: keep RWY pop (above) before intro callsign (below) in case list starts with RWY name
	#     with L/C/R suffix and without "runway" prefix (RWY would be stripped of its numbers)
	addressee_tokens = pop_intro_callsign(tokens)
	recognised_instructions = []
	finished = False
	while not finished:
		instr = pop_one_instruction(tokens, sfc_to_expect)
		if instr is None:
			finished = True
		else:
			recognised_instructions.append(instr)
	return addressee_tokens, recognised_instructions



def pop_one_instruction(tokens, sfc_to_expect):
	# Instruction.CANCEL_APP
	try:
		try:
			i = tokens.index('go-around')
			j = i + 1
		except ValueError:
			i = tokens.index('cancel') # cf. "cancel approach"
			j = i + 2
	except ValueError:
		pass
	else:
		SR_log('RECOGNISED: cancel app', tokens)
		del tokens[i:j]
		return Instruction(Instruction.CANCEL_APP)
	
	# Instruction.EXPECT_SFC
	try:
		i = tokens.index('expect')
	except ValueError:
		pass
	else:
		# 'j' below is last index to remove once instr is recognised; runway tokens are already removed
		j_max = min(len(tokens), i+3)
		j = next((j for j in range(i+1, j_max) if tokens[j] not in ['ils', 'visual', 'straight-in', 'approach']), j_max)
		app = next((b for t, b in app_type_tokens.items() if t in tokens[i+1 : j+1]), None)
		SR_log('RECOGNISED: rwy/app', sfc_to_expect, app, tokens)
		del tokens[i : j+1]
		return Instruction(Instruction.EXPECT_SFC, arg=(sfc_to_expect if sfc_to_expect else None), arg2=app)
	
	# Instruction.VECTOR_HDG
	try:
		turn_dir = None
		try:
			i = tokens.index('turn')
			if tokens[i+1] == 'right':
				turn_dir = True
			elif tokens[i+1] == 'left':
				turn_dir = False
		except ValueError:
			i = tokens.index('heading')
	except ValueError:
		pass
	else:
		try:
			ni, ntk = find_num_tokens(tokens, i + 1)
			hdg = convert_num_tokens(ntk)
		except ValueError as err:
			SR_log('Please report bug with heading instruction: %s' % err, tokens)
		else:
			SR_log('RECOGNISED: hdg', hdg, tokens)
			del tokens[i : ni+len(ntk)]
			return Instruction(Instruction.VECTOR_HDG, arg=Heading(hdg, False), arg2=turn_dir)
	
	# Instruction.VECTOR_ALT
	try:
		ifl = tokens.index('flight-level') # "flight level"
	except ValueError: # try altitude
		th = hu = None
		try:
			ith = tokens.index('thousand')
			nith, thtk = find_num_tokens(tokens, ith - 1, bwd=True)
			del tokens[nith : ith+1]
			SR_log('Tokens left after "thousand":', tokens)
			th = convert_num_tokens(thtk) # STYLE catch a fail here?
		except ValueError:
			pass
		try:
			ihu = tokens.index('hundred')
			nihu, hutk = find_num_tokens(tokens, ihu - 1, bwd=True)
			del tokens[nihu : ihu+1]
			SR_log('Tokens left after "hundred":', tokens)
			hu = convert_num_tokens(hutk) # STYLE catch a fail here?
		except ValueError:
			pass
		if th is not None or hu is not None: # got altitude
			alt = 1000 * some(th, 0) + 100 * some(hu, 0)
			SR_log('RECOGNISED: alt', alt)
			return Instruction(Instruction.VECTOR_ALT, arg=AltFlSpec(False, alt))
	else: # got FL
		try:
			nifl, fltk = find_num_tokens(tokens, ifl + 1)
			fl = convert_num_tokens(fltk)
		except ValueError as err:
			SR_log('Please report bug with FL instruction: %s' % err, tokens)
		else:
			SR_log('RECOGNISED: FL', fl, tokens)
			del tokens[ifl : nifl+len(fltk)]
			return Instruction(Instruction.VECTOR_ALT, arg=AltFlSpec(True, fl))
	
	# Instruction.VECTOR_SPD
	try:
		i = tokens.index('speed')
	except ValueError:
		pass
	else:
		if tokens[i+1 : i+3] == ['your', 'discretion']:
			SR_log('RECOGNISED: cancel spd')
			del tokens[i : i+3]
			return Instruction(Instruction.CANCEL_SPD)
		else:
			try:
				ni, ntk = find_num_tokens(tokens, i + 1)
				spd = convert_num_tokens(ntk)
			except ValueError as err:
				SR_log('Please report bug with speed instruction: %s' % err, tokens)
			else:
				SR_log('RECOGNISED: spd', spd, tokens)
				del tokens[i : ni+len(ntk)]
				return Instruction(Instruction.VECTOR_SPD, arg=Speed(spd))
	
	# Instruction.SQUAWK
	try:
		i = tokens.index('squawk')
	except ValueError:
		pass
	else:
		sq = [digit_tokens[tokens[k]] for k in range(i+1, i+5)]
		sq_code = 8*8*8 * sq[0] + 8*8 * sq[1] + 8 * sq[2] + sq[3]
		SR_log('RECOGNISED: sq', sq_code, tokens)
		del tokens[i : i+5]
		return Instruction(Instruction.SQUAWK, arg=sq_code)
	
	# Instruction.HAND_OVER
	try:
		i = tokens.index('contact')
	except ValueError:
		pass
	else:
		try:
			atc = atc_tokens[tokens[i+1]]
		except (KeyError, IndexError) as err:
			SR_log('Please report bug with h/o instruction: %s' % err, tokens)
		else:
			SR_log('RECOGNISED: handover', tokens)
			del tokens[i : i+2]
			return Instruction(Instruction.HAND_OVER, arg=atc)
	
	# Instruction.INTERCEPT_LOC
	try:
		iloc = tokens.index('localiser')
		i, tk = find_tokens('intercept'.__eq__, tokens, iloc - 1, True)
	except ValueError:
		pass
	else:
		SR_log('RECOGNISED: loc', tokens)
		del tokens[i : iloc+1]
		return Instruction(Instruction.INTERCEPT_LOC, arg=(sfc_to_expect if sfc_to_expect else None))
	
	# Instruction.CLEARED_APP
	try:
		try: #TODO "make straight-in" without "approach"
			iapp = tokens.index('approach') # WARNING "approach" also appears in CANCEL_APP, EXPECT_SFC and HAND_OVER, but should be removed by now
		except ValueError:
			iapp = tokens.index('ils') # WARNING "ils" also appears in EXPECT_SFC, but should be removed by now
		i, tk1_ignore = find_tokens('cleared'.__eq__, tokens, iapp - 1, True)
	except ValueError:
		pass
	else:
		app = next((b for t, b in app_type_tokens.items() if t in tokens[i+1 : iapp+1]), None)
		SR_log('RECOGNISED: app', app, tokens)
		del tokens[i : iapp+1]
		return Instruction(Instruction.CLEARED_APP, arg=(sfc_to_expect if sfc_to_expect else None), arg2=app)
	
	# Instruction.LINE_UP
	try:
		i = tokens.index('wait')
	except ValueError:
		pass
	else:
		SR_log('RECOGNISED: luw', tokens)
		del tokens[i-2 : i+1]
		return Instruction(Instruction.LINE_UP, arg=(sfc_to_expect if sfc_to_expect else None))
	
	# Instruction.CLEARED_TKOF
	try:
		i = tokens.index('take-off')
	except ValueError:
		pass
	else:
		SR_log('RECOGNISED: cto', tokens)
		del tokens[i-2 : i+1]
		return Instruction(Instruction.CLEARED_TKOF, arg=(sfc_to_expect if sfc_to_expect else None))
	
	# Instruction.CLEARED_LDG
	try:
		i = tokens.index('land')
	except ValueError:
		pass
	else:
		SR_log('RECOGNISED: ctl', tokens)
		del tokens[i-2 : i+1]
		return Instruction(Instruction.CLEARED_LDG, arg=(sfc_to_expect if sfc_to_expect else None))
	
	# Instruction.SAY_INTENTIONS
	try:
		i = tokens.index('intentions')
	except ValueError:
		pass
	else:
		SR_log('RECOGNISED: intentions?', tokens)
		del tokens[i-1 : i+1]
		return Instruction(Instruction.SAY_INTENTIONS)
	
	# Instruction.VECTOR_DCT
	try:
		i = tokens.index('proceed')
	except ValueError:
		pass
	else:
		try:
			pi, ptk = find_tokens(is_navpoint_token, tokens, i + 1, False)
			point = convert_navpoint_tokens(ptk)
		except ValueError as err:
			SR_log('Please report bug with DCT instruction: %s' % err, tokens)
		else:
			SR_log('RECOGNISED: dct', point, tokens)
			del tokens[i : pi+len(ptk)]
			return Instruction(Instruction.VECTOR_DCT, arg=point)
	
	# Instruction.HOLD_AT_FIX, Instruction.HOLD_POSITION
	try:
		i = tokens.index('hold')
	except ValueError:
		pass
	else:
		if i + 1 < len(tokens) and tokens[i+1] == 'position':
			SR_log('RECOGNISED: hold-position', tokens)
			del tokens[i:i+2]
			return Instruction(Instruction.HOLD_POSITION)
		else:
			try:
				pi, ptk = find_tokens(is_navpoint_token, tokens, i + 1, False)
				point = convert_navpoint_tokens(ptk)
			except ValueError as err:
				SR_log('Please report bug with hold instruction: %s' % err, tokens)
			else:
				SR_log('RECOGNISED: hold-at-fix', point, tokens)
				del tokens[i : pi+len(ptk)]
				return Instruction(Instruction.HOLD_AT_FIX, arg=point)









def radio_callsign_match(tokens, target):
	"""
	"tokens" is list; "target" is str
	CAUTION "target" need not be strictly alpha-num, e.g. it may contain "-"
	"""
	if len(tokens) == 0:
		return False
	elif tokens[0].startswith(airline_token_prefix):
		return write_radio_callsign(tokens) == target
	else: # spelling out callsign with alpha-nums
		called = [write_alphanum(tok) for tok in tokens]
		tail_chars_matched = 0
		while len(called) > 0 and len(target) > tail_chars_matched and called[-1] == target[-1 - tail_chars_matched]:
			tail_chars_matched += 1
			called.pop()
		return 2 <= tail_chars_matched < len(target) and target.startswith(''.join(called))


def write_radio_callsign(tokens):
	if tokens[0].startswith(airline_token_prefix):
		airline = tokens[0][len(airline_token_prefix):]
		irgt = -1 if tokens[-1] in num2digit_tokens else -2
		num_lft = 0 if tokens[1:irgt] == [] else convert_num_tokens(tokens[1:irgt])
		num_rgt = convert_num_tokens(tokens[irgt:])
		return '%s%02d%02d' % (airline, num_lft, num_rgt)
	else:
		return '-'.join(write_alphanum(tok) for tok in tokens)



def pop_intro_callsign(tokens):
	if tokens[0].startswith(airline_token_prefix):
		i = 1
		digit_count = 0 # max 4 digits in flight number (avoids stepping into other num tokens if they follow, e.g. RWY name for landing clearance)
		while i < len(tokens) and digit_count < 4 and is_num_token(tokens[i]) and not (i + 1 < len(tokens) and tokens[i+1] in rwy_suffix_tokens):
			if tokens[i] in digit_tokens or tokens[i] in num2digit_tokens and i + 1 < len(tokens) and digit_count < 3 and tokens[i+1] in digit_tokens:
				digit_count += 1 # single digit OR counting this token as tens and next digit as units
			else: # tokens[i] in num2digit_tokens
				digit_count += 2
			i += 1
	else:
		i = next((i for i, tok in enumerate(tokens) if not is_alphanum_token(tok)), len(tokens))
	res_tokens = tokens[:i]
	del tokens[:i]
	return res_tokens



def pop_named_depldgsfc(tokens):
	i = 0
	res_sfc_names = set()
	while i < len(tokens) - 1:
		if i < len(tokens) - 2 and tokens[i] in digit_tokens and tokens[i+1] in digit_tokens and tokens[i+2] in rwy_suffix_tokens \
				or tokens[i] in num2digit_tokens and tokens[i+1] in rwy_suffix_tokens:
			tokens.insert(i, 'runway')
		if tokens[i] == 'runway':
			j, tk = find_num_tokens(tokens, i + 1)
			ic = j+len(tk)
			try:
				suf = rwy_suffix_tokens[tokens[ic]]
				ic += 1
			except (KeyError, IndexError):
				suf = ''
			res_sfc_names.add('%02d%s' % (convert_num_tokens(tk), suf))
			del tokens[i:ic]
		elif tokens[i] == 'helipad':
			j, tk = find_tokens(is_alphanum_token, tokens, i + 1, False)
			res_sfc_names.add('H%d' % convert_num_tokens(tk)) #FIXME tokens could be <alphanum>+
			del tokens[i : j+len(tk)]
		else:
			i += 1
	return res_sfc_names







## ## ## ##    TOKEN UTILS    ## ## ## ##

def is_num_token(tok):
	return tok in digit_tokens or tok in num2digit_tokens

def is_alphanum_token(tok):
	return tok in letter_tokens or is_num_token(tok)

def is_navpoint_token(tok):
	return is_alphanum_token(tok) or tok.startswith(navpoint_token_prefix)

def find_num_tokens(lst, i, bwd=False):
	return find_tokens(is_num_token, lst, i, bwd)

def find_tokens(pred, lst, i, bwd):
	res_tokens = []
	while 0 <= i < len(lst) and not pred(lst[i]):
		i += -1 if bwd else 1
	if 0 <= i < len(lst):
		res_index = i
		while 0 <= i < len(lst) and pred(lst[i]):
			res_tokens.append(lst[i])
			i += 1
		if bwd:
			res_tokens.reverse()
		return res_index, res_tokens
	else:
		raise ValueError('no token found')

def write_alphanum(tok):
	try:
		return letter_tokens[tok]
	except KeyError:
		return str(convert_num_tokens([tok]))

def convert_num_tokens(lst):
	try:
		if len(lst) == 1:
			try:
				return digit_tokens[lst[0]] # e.g. "one" = 1
			except KeyError:
				return num2digit_tokens[lst[0]] # e.g. "twenty" = 20
		elif len(lst) == 2:
			if lst[0] in digit_tokens:
				try:
					return 10 * digit_tokens[lst[0]] + digit_tokens[lst[1]] # e.g. "one zero" = 10
				except KeyError:
					return 100 * digit_tokens[lst[0]] + num2digit_tokens[lst[1]] # e.g. "one eighty" = 180
			else:
				return num2digit_tokens[lst[0]] + digit_tokens[lst[1]] # e.g. "eighty one" = 81
		elif len(lst) == 3:
			if all(tok in digit_tokens for tok in lst):
				return 100 * digit_tokens[lst[0]] + 10 * digit_tokens[lst[1]] + digit_tokens[lst[2]] # e.g. "one eight zero" = 180
			else:
				try:
					left = 10 * digit_tokens[lst[0]] + digit_tokens[lst[1]]
					right = num2digit_tokens[lst[2]]
					if left == right:
						return left # e.g. "one one eleven" = 11
				except KeyError:
					return 100 * digit_tokens[lst[0]] + num2digit_tokens[lst[1]] + digit_tokens[lst[2]] # e.g. "two eighty one" = 281
		elif len(lst) == 4:
				left = 10 * digit_tokens[lst[0]] + digit_tokens[lst[1]]
				right = num2digit_tokens[lst[2]] + digit_tokens[lst[3]]
				if left == right:
					return left # e.g. "two one twenty one" = 21
	except KeyError:
		pass
	raise ValueError('Cannot convert num: %s' % ' '.join(lst))

def convert_navpoint_tokens(lst):
	if len(lst) == 1 and lst[0].startswith(navpoint_token_prefix):
		return lst[0][len(navpoint_token_prefix):]
	else:
		return ''.join(write_alphanum(tk) for tk in lst)



## TOKENS

digit_tokens = {
	'zero': 0, 'o': 0,
	'one': 1,
	'two': 2,
	'three': 3, 'tree': 3,
	'four': 4,
	'five': 5, 'fife': 5,
	'six': 6,
	'seven': 7,
	'eight': 8,
	'nine': 9, 'niner': 9,
}

num2digit_tokens = {
	'ten': 10,
	'eleven': 11,
	'twelve': 12,
	'thirteen': 13,
	'fourteen': 14,
	'fifteen': 15,
	'sixteen': 16,
	'seventeen': 17,
	'eighteen': 18,
	'nineteen': 19,
	'twenty': 20,
	'thirty': 30,
	'forty': 40,
	'fifty': 50,
	'sixty': 60,
	'seventy': 70,
	'eighty': 80,
	'ninety': 90
}

letter_tokens = {
	'alpha': 'A',
	'bravo': 'B',
	'charlie': 'C',
	'delta': 'D',
	'echo': 'E',
	'foxtrot': 'F', 'fox': 'F',
	'golf': 'G',
	'hotel': 'H',
	'india': 'I',
	'juliet': 'J',
	'kilo': 'K',
	'lima': 'L',
	'mike': 'M',
	'november': 'N',
	'oscar': 'O',
	'papa': 'P',
	'quebec': 'Q',
	'romeo': 'R',
	'sierra': 'S',
	'tango': 'T',
	'uniform': 'U',
	'victor': 'V',
	'whiskey': 'W',
	'x-ray': 'X',
	'yankee': 'Y',
	'zulu': 'Z'
}

rwy_suffix_tokens = {
	'left': 'L',
	'right': 'R',
	'centre': 'C'
}

app_type_tokens = {
	'ils': ApproachType.ILS,
	'visual': ApproachType.VISUAL,
	'straight-in': ApproachType.STRAIGHT_IN
}

atc_tokens = {
	'ramp': 'Ramp',
	'ground': 'GND',
	'tower': 'TWR',
	'departure': 'DEP',
	'approach': 'APP',
	'radar': 'CTR',
	'centre': 'CTR'
}
