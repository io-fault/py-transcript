"""
# Status frame I/O support.
"""
import sys
import os
import io

from ..system import execution
from ..status import frames as st_frames

def spawnframes(invocation,
		exceptions=sys.stderr,
		stdin=sys.stdin.fileno(),
		stderr=sys.stderr.fileno(),
	):
	"""
	# Generator emitting frames produced by the given invocation's standard out.
	"""
	loadframe = st_frames.stdio()[0]

	rfd, wfd = os.pipe()
	pid = invocation.spawn(fdmap=[(stdin,0), (wfd,1), (stderr,2)])

	try:
		os.close(wfd)

		framesrc = io.TextIOWrapper(io.BufferedReader(io.FileIO(rfd, mode='r'), 2048), 'utf-8')
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
				lines = framesrc.readlines(1024*8)
	except:
		raise
	finally:
		procx = execution.reap(pid, options=0)
		if procx.status != 0:
			sys.stderr.write("WARNING: status frame source exited with non-zero result\n")
