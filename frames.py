"""
# Status frame logging.
"""
import os
import typing

from ..context import tools
from ..status import types

protocol = 'http://if.fault.io/status/metrics'

def metrics(time:int, units, counts:typing.Mapping[str,int], synopsis="deltas", protocol=protocol):
	"""
	# Construct a metrics report for conveying operation progress.
	"""
	r_params = types.Parameters.from_nothing_v1()
	r_params['time'] = time

	units = dict(units)
	for k, v in counts.items():
		if k not in units:
			units[k] = v
			counts[k] = 0 # Identifies as pure count.

	kv = list(units.items())
	r_params.specify([
		('v-sequence', 'string', 'fields', [x[0] for x in kv]),
		('v-sequence', 'rational', 'units', [x[1] for x in kv]),
		('v-sequence', 'integer', 'counts', [counts.get(x[0], 0) for x in kv]),
	])

	return types.Report.from_string_v1(
		"units-and-counts[1]: " + synopsis,
		protocol=protocol,
		parameters=r_params,
	)

class Log(object):
	"""
	# Status frame serialization buffer.
	"""

	@classmethod
	def stdout(Class, encoding=None):
		"""
		# Construct a &Log instance for serializing frames to &sys.stdout.
		"""
		from sys import stdout
		from ..status import frames
		return Class(frames.stdio()[1], stdout.buffer, encoding or stdout.encoding)

	@classmethod
	def stderr(Class, encoding=None):
		"""
		# Construct a &Log instance for serializing frames to &sys.stderr.
		"""
		from sys import stderr
		from ..status import frames
		return Class(frames.stdio()[1], stderr.buffer, encoding or stderr.encoding)

	def __init__(self, pack, stream, encoding, frequency=8):
		self.encoding = encoding
		self.frequency = frequency
		self.stream = stream
		self._pack = pack
		self._send = stream.write
		self._flush = stream.flush
		self._count = 0

	def transaction(self) -> bool:
		"""
		# Increment the operation count and check if it exceeds the frequency.
		# If in excess, flush the buffer causing serialized messages to be written
		# to the configured stream.

		# Return &True when a &flush is performed, otherwise &False.
		"""
		self._count += 1
		if self._count >= self.frequency:
			self.flush()
			return True
		return False

	def flush(self):
		"""
		# Write any emitted messages to the configured stream and reset the operation count.
		"""
		self._count = 0
		self._flush()

	def emit(self, channel, message):
		"""
		# Send a &message using the given &channel identifier.
		"""
		return self._send(self._pack((channel, message)).encode(self.encoding))

	def write(self, text:str):
		"""
		# Write text to the log's stream incrementing the transmit count.
		"""
		self._send(text.encode(self.encoding))
		self._count += 1
