"""
# Terminal support for status displays.
"""
import os
import io
import typing
from ..terminal import matrix

class Monitor(object):
	"""
	# Allocated area for status display.

	# Structure holding the target &matrix.Context with the rendering
	# function and an associated state snapshot.
	"""
	Render = typing.Callable[[matrix.Context, object], bytes]

	def __init__(self, render:Render, context:matrix.Context, state:object):
		self.state = state
		self.render = render
		self.context = context

	def replace(self, state):
		self.state = state

	def update(self):
		return self.render(self.context, self.state)

def separators(fields:int, pad=", "):
	for x in range(fields-1):
		yield pad

	yield "."

class Control(object):
	"""
	# Root monitor control; manages the device interface, screen, and status context.
	"""

	def __init__(self, device, screen, context):
		self.device = device
		self.screen = screen
		self.context = context

		self.Normal = context.terminal_type.normal_render_parameters
		self.Key = self.Value = self.Space = self.Field = self.Normal

		self._io = io.FileIO(device.fileno(), closefd=False, mode='w')
		self._prefix = ""

	def initialize(self, order):
		self._prefix = None
		self._suffix = None
		self.field_order = order
		self.field_values = {}
		self.field_value_override = {}
		self.field_label_override = {}

	def prefix(self, *words):
		self._prefix = words

	def suffix(self, *words):
		self._suffix = words

	def fields(self):
		return zip(self.field_order, separators(len(self.field_order)))

	def render(self):
		if self._prefix:
			yield from self._prefix
			yield self.Space.form(" ")

		for k, fpad in self.fields():
			v = self.field_values.get(k, None)
			if v is None:
				continue

			rp = self.field_value_override.get(k, self.Value)

			#yield self.Key.form(k.capitalize() + ":")
			yield rp.form(str(v))
			yield self.Space.form(" ")
			yield self.Key.form(self.field_label_override.get(k, k))
			yield self.Space.form(fpad)

		if self._suffix:
			yield from self._suffix

	def update(self, fields):
		ctx = self.context
		self.field_values.update(fields)

		buf = self.screen.exit_scrolling_region() + ctx.seek_first()

		l = ctx.Phrase.from_words(*self.render())
		i = ctx.print([l], [l.cellcount()])

		buf += b''.join(i)
		buf += self.screen.enter_scrolling_region()

		self._io.write(buf)
		self._io.flush()

	def flush(self):
		l = self.context.Phrase.from_words(*self.render())
		return b''.join(self.context.render(l)).decode('utf-8')

	def clear(self):
		clean = self.screen.exit_scrolling_region()
		clean += self.context.clear()
		clean += self.screen.enter_scrolling_region()
		os.write(self.device.fileno(), clean)

def setup(lines:int, atexit=b'', type='prepared',
		destruct=True, Context=matrix.Context,
	) -> Control:
	"""
	# Initialize the terminal for use with a scrolling region.

	# The given &lines determines the area allocation to
	# manage at the bottom of the screen.
	"""
	if not lines:
		raise ValueError("line allocation must be non-zero")

	from ..terminal import control
	screen = matrix.Screen()

	device = control.setup(type,
		atexit=screen.close_scrolling_region()+atexit,
		destruct=destruct,
	)

	hv = device.get_window_dimensions()
	screen.context_set_dimensions(hv)

	ctx = Context(screen.terminal_type)
	if lines > 0:
		t = 0
		v = hv[1] - lines

		ctx.context_set_position((0, v))
		ctx.context_set_dimensions((hv[0], lines))
		init = (b'\n' * lines) + screen.seek_vertical_relative(-lines)
	else:
		# Allocate top.
		t = -lines
		v = hv[1]

		ctx.context_set_position((0, 0))
		ctx.context_set_dimensions((hv[0], -lines))
		init = screen.store_cursor_location() + ctx.clear() + screen.restore_cursor_location()

	init += screen.open_scrolling_region(t, v-1)
	os.write(device.fileno(), init)
	return Control(device, screen, ctx)

if __name__ == '__main__':
	import time
	st_ctl = setup(1, width=80)
	st_ctl.initialize(['field-1', 'field-2'])
	st_ctl.update({'field-1': 0, 'field-2': 'test'})
	print('test-1')
	time.sleep(1)
	st_ctl.update({'field-1': 6, 'field-2': 'test-2'})
	print('test-2')
	time.sleep(2)
