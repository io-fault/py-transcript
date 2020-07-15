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
from ..status import frames as st_frames

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
	loadframe, packframe = st_frames.stdio()

	rfd, wfd = os.pipe()
	pid = invocation.spawn(fdmap=[(stdin,0), (wfd,1), (stderr,2)])

	try:
		os.close(wfd)

		framesrc = allocate_line_buffer(rfd)
		with framesrc:
			lines = [framesrc.readline()] # Protocol message.
			while lines:
				frames = []
				for line in lines:
					try:
						frames.append(loadframe(line))
					except:
						# Any exception means it's not a well formed frame.
						# In such cases, relay the original line to standard error.
						exceptions.write('> ' + line)
					finally:
						pass
				yield frames
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

	def __init__(self, readframe, encoding='utf-8', newline=b'\n', timeout=145):
		self.timeout = timeout
		self.newline = newline
		self.encoding = encoding
		self.unpack = readframe
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
			return self.unpack(line.decode(self.encoding))
		except Exception as err:
			pass

	def collect(self):
		with self._ioa.wait(self.timeout):
			return [
				(channel.link, channel.transfer(), channel.terminated, channel)
				for channel in self._ioa.transfer()
			]

	def __iter__(self):
		unpack = self.unpack

		for rid, data, term, channel in self.collect():
			frames = []
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
				frames.extend(map(self.frame, lines))

			del buffer

			if term:
				# Finish buffer.
				buffer = self._linebuffers.pop(rid)
				if buffer:
					# Force newline.
					if not buffer.endswith(self.newline):
						buffer += self.newline

					lines = buffer.splitlines(keepends=True)
					frames.extend(map(self.frame, lines))

				yield (rid, frames)
				yield (rid, None)
			elif channel.exhausted:
				# Only reads.
				channel.acquire(bytearray(1028*8))
				yield (rid, frames)
			else:
				yield (rid, frames)
