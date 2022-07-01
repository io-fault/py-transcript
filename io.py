"""
# Status frame I/O support.
"""
import sys
import os
import io
import itertools
import signal

from ..context import tools
from ..system import execution
from ..status import frames

def allocate_line_buffer(fd, encoding='utf-8'):
	return io.TextIOWrapper(io.BufferedReader(io.FileIO(fd, mode='r'), 2048), encoding)

def spawnframes(invocation,
		exceptions=sys.stderr,
		stdin=sys.stdin.fileno(),
		stderr=sys.stderr.fileno(),
		readsize=1024*4,
	):
	"""
	# Generator emitting frames produced by the given invocation's standard out.
	# If &GeneratorExit or &KeyboardInterrupt is thrown, the generator will send
	# the process a &signal.SIGKILL.
	"""
	interrupted = False

	rfd, wfd = os.pipe()
	pid = invocation.spawn(fdmap=[(stdin,0), (wfd,1), (stderr,2)])

	try:
		os.close(wfd)

		framesrc = allocate_line_buffer(rfd)
		with framesrc:
			lines = [framesrc.readline()] # Protocol message.
			while lines:
				frameset = []
				for line in lines:
					try:
						frameset.append(frames.structure(line))
					except:
						# Any exception means it's not a well formed frame.
						# In such cases, relay the original line to standard error.
						exceptions.write('> ' + line)
					finally:
						pass
				yield frameset
				lines = framesrc.readlines(readsize)
	except (GeneratorExit, KeyboardInterrupt) as exc:
		interrupted = True
		try:
			os.killpg(pid, signal.SIGKILL)
		except ProcessLookupError:
			pass

		raise exc
	finally:
		procx = execution.reap(pid, options=0)
		if not interrupted and procx.status != 0:
			exceptions.write("[!# WARNING: status frame source exited with non-zero result]\n")

class FrameArray(object):
	"""
	# IO array manager for frame sources.
	"""

	@tools.cachedproperty
	def io(self):
		from ..system import io
		return (io.Array, io.alloc_input)

	def __init__(self,
		readframe=frames.structure,
		encoding='utf-8', newline=b'\n', timeout=145
	):
		self.timeout = timeout
		self.newline = newline
		self.encoding = encoding
		self._unpack = readframe
		self._ioa = None
		self._linebuffers = {}

	def __enter__(self):
		if self._ioa is None:
			self._ioa = self.io[0]()

	def __exit__(self, exc, val, tb):
		self._ioa.void()

	def connect(self, id, fd):
		channel = self.io[1](fd)
		channel.link = id
		self._ioa.acquire(channel)
		channel.acquire(bytearray(1024*8))
		self._linebuffers[id] = bytearray()

	def force(self):
		self._ioa.force()

	def frame(self, line):
		"""
		# Decode and unpack the binary status frame using Array's configuration.
		"""
		try:
			return self._unpack(line.decode(self.encoding))
		except Exception as err:
			pass

	def collect(self):
		with self._ioa.wait(self.timeout):
			return [
				(channel.link, channel.transfer(), channel.terminated, channel)
				for channel in self._ioa.transfer()
			]

	def __iter__(self):
		unpack = self._unpack

		for rid, data, term, channel in self.collect():
			frameset = []
			buffer = self._linebuffers[rid]
			buffer += data

			if buffer:
				lines = buffer.splitlines(keepends=True)
				if buffer.endswith(self.newline):
					self._linebuffers[rid] = bytearray()
				else:
					# Maintain buffer.
					self._linebuffers[rid] = lines[-1]
					del lines[-1:]

				# Emit empty to signal that some buffer change occurred.
				frameset.extend(map(self.frame, lines))

			del buffer

			if term:
				# Finish buffer.
				buffer = self._linebuffers.pop(rid)
				if buffer:
					# Force newline.
					if not buffer.endswith(self.newline):
						buffer += self.newline

					lines = buffer.splitlines(keepends=True)
					frameset.extend(map(self.frame, lines))

				yield (rid, frameset)
				yield (rid, None)
			elif channel.exhausted:
				# Only reads.
				channel.acquire(bytearray(1028*8))
				yield (rid, frameset)
			else:
				yield (rid, frameset)

class Log(object):
	"""
	# Status frame serialization interface and write buffer.
	"""

	#* REFACTOR: Parameterize theme so host/user specific overrides may be employed.
	highlights = {
		'reset': '\x1b[0m',
		'error': '\x1b[31m',
		'warning': '\x1b[33m',
		'notice': '\x1b[34m',
		'synopsis': '\x1b[38;5;247m',
	}

	@staticmethod
	def _xid(extension, xid):
		if xid:
			if extension is None:
				extension = {}
			extension['@transaction'] = xid.split('\n')

		return extension

	@classmethod
	def stdout(Class, channel=None, encoding=None):
		"""
		# Construct a &Log instance for serializing frames to &sys.stdout.
		"""
		from sys import stdout
		return Class(frames.sequence, stdout.buffer, encoding or stdout.encoding, channel=channel)

	@classmethod
	def stderr(Class, channel=None, encoding=None):
		"""
		# Construct a &Log instance for serializing frames to &sys.stderr.
		"""
		from sys import stderr
		return Class(frames.sequence, stderr.buffer, encoding or stderr.encoding, channel=channel)

	def __init__(self, pack, stream, encoding, frequency=8, channel=None):
		self.channel = channel
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

	def emit(self, frame):
		"""
		# Send a &message using the given &channel identifier.
		"""
		return self._send(self._pack(frame, channel=self.channel).encode(self.encoding))

	def inject(self, data:bytes):
		"""
		# Write bytes directly to the log's stream.
		"""
		self._send(data)
		self._count += 1

	def write(self, text:str):
		"""
		# Write text to the log's stream incrementing the transmit count.
		"""
		self._send(text.encode(self.encoding))
		self._count += 1

	def declare(self, datum='2000-01-02', timestamp=0):
		"""
		# Emit a protocol declaration.
		"""
		ext = {
			'@timestamp': [str(timestamp)],
			'@clock': ['metric-seconds -9 ' + datum],
		}
		self.emit(frames.declaration())

	def compose(self, type, severity, qualifier, text, extension,
			channel=None,
			_compose=frames.compose
		):
		sy = self.highlights['synopsis']
		re = self.highlights['reset']
		syn = ''.join([
			self.highlights[severity],
			qualifier, re,
			sy, ': ', text[0]
		])

		hi = itertools.cycle((re, sy))
		for seg, hi in zip(text[1:], hi):
			if seg:
				syn += hi + seg

		if len(text) % 2 == 1:
			syn += re

		if channel is None:
			channel = self.channel

		return _compose(type, syn, channel, extension or {})

	def notice(self, *text, extension=None, xid=None, label='NOTICE'):
		extension = self._xid(extension, xid)
		msg = self.compose('!#', 'notice', label, text, extension)
		self.emit(msg)
		return msg

	def warning(self, *text, extension=None, xid=None, label='WARNING'):
		extension = self._xid(extension, xid)
		msg = self.compose('!#', 'warning', label, text, extension)
		self.emit(msg)
		return msg

	def error(self, *text, extension=None, xid=None, label='ERROR'):
		extension = self._xid(extension, xid)
		msg = self.compose('!#', 'error', label, text, extension)
		self.emit(msg)
		return msg

	def xact_open(self, xid, synopsis, extension):
		extension = self._xid(extension, xid)
		f = frames.compose("->", synopsis, self.channel, extension)
		self.emit(f)
		return f

	def xact_status(self, xid, synopsis, extension):
		extension = self._xid(extension, xid)
		f = frames.compose('--', synopsis, self.channel, extension)
		self.emit(f)
		return f

	def xact_close(self, xid, synopsis, extension):
		extension = self._xid(extension, xid)
		f = frames.compose("<-", synopsis, self.channel, extension)
		self.emit(f)
		return f
