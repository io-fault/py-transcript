"""
# Terminal support for status displays.
"""
import os
import io
import typing
import itertools
import collections

from ..context import tools
from ..terminal import matrix
from ..time import sysclock

def duration_repr(seconds) -> typing.Tuple[float, str]:
	if seconds < 60:
		return (seconds / 1.0, 's')
	elif seconds < (60*60):
		# minutes
		return (seconds / 60, 'm')

	hours = seconds / (60*60)
	if hours < 100:
		return (hours, 'h')

	return (hours / 24, 'd')

class Layout(object):
	"""
	# The set, sizes, and ordering of fields present in a monitor.
	"""
	Definition = typing.Tuple[str, int]
	Fields = typing.Sequence[Definition]

	@staticmethod
	def separators(fields:int, termination=".", separation=", "):
		"""
		# Generate a series of separators finished with a terminator.
		# Given a number of a fields, emit separators until the final index
		# is reached.
		"""

		for x in range(fields-1):
			yield separation

		yield termination

	def label(self, field, text:str):
		"""
		# The display text for the field's label.
		"""
		self.labels[field] = text

	def __init__(self, fields:Fields):
		self.labels = {}
		self.order = [x[0] for x in fields]
		self.cells = dict(fields)

	def fields(self):
		"""
		# Iterate over the fields in their designated order along with separators
		# that can be used to follow the rendered field.
		"""
		return zip(self.order, self.separators(len(self.order)))

class Theme(object):
	"""
	# The rendering methods and parameters used by a &Monitor.
	"""
	Formatter = typing.Tuple[str, str]

	def default_render_method(self, key, field):
		"""
		# Renders the string form of &field with the style set identified
		# by &key.
		"""
		return [
			('plain' if key not in self.stylesets else key, str(field)),
		]

	@staticmethod
	def r_duration(value):
		"""
		# Render method for common duration fields.
		"""
		time, precision = duration_repr(value)
		string = "{:.1f}".format(value)

		return [
			('duration', string),
			(precision+'-timeunit', precision),
		]

	def define(self, name, *args, **kw):
		"""
		# Define a set of render parameters within the theme.
		# Parameters aside from &name are passed to &matrix.Context.RenderParameters.apply.
		"""
		self.stylesets[name] = self.stylesets['plain'].apply(*args, **kw)

	def implement(self, type, render):
		"""
		# Assign a render method, &call, for the &field.
		"""
		self.rendermethod[type] = render

	def __init__(self, default:matrix.Context.RenderParameters):
		from ..terminal import palette
		self.rendermethod = {}
		plain = default.apply()
		self.stylesets = {
			# Time is expected to be common among all themes.
			'plain': plain,
			'bold': plain.apply('bold'),
			's-timeunit': plain.apply(textcolor=palette.colors['blue']),
			'm-timeunit': plain.apply(textcolor=palette.colors['yellow']),
			'h-timeunit': plain.apply(textcolor=palette.colors['orange']),
			'd-timeunit': plain.apply(textcolor=palette.colors['red']),
			'Label': plain.apply(textcolor=palette.colors['foreground-adjacent']),
			'Label-Emphasis': plain.apply('bold', textcolor=palette.colors['foreground-adjacent']),
		}

	def style(self, celltexts:typing.Sequence[Formatter]):
		"""
		# Emit words formatted according to their associated style set for forming
		# a &matrix.Context.Phrase instance.
		"""
		idx = self.stylesets
		for style_idx, text in celltexts:
			yield idx[style_idx].form(text)

		yield idx['plain'].form('')

	def render(self, type, field, Phrase=matrix.Context.Phrase.from_words, partial=tools.partial):
		"""
		# Render the given &field according to the configured &type' render method.
		"""
		r_method = self.rendermethod.get(type) or partial(self.default_render_method, type)
		return Phrase(*self.style(r_method(field)))

class Monitor(object):
	"""
	# Allocated area for status display of a set of changing fields.

	# Structure holding the target &matrix.Context with the rendering
	# function and an associated state snapshot.

	# [ Engineering ]
	# &Monitor and &Theme have an instance and type relationship. In this case,
	# &Theme controls the formatting and styles of the field *contents*, and
	# &Monitor controls field placement and context(prefix and suffix).
	"""

	def __init__(self, theme:Theme, layout:Layout, context:matrix.Context):
		self.context = context
		self.layout = layout
		self.theme = theme

		# Monitor local:
		self._image = {}
		self._prefix = None
		self._suffix = None
		self._positions = list(self._calculate_fields())

	def _calculate_fields(self, alignment=1):
		Phrase = self.context.Phrase
		position = 0

		fl = self.layout.labels
		cc = self.layout.cells
		for f in self.layout.order:
			cells = cc[f]
			label = self.theme.render('label-'+f, fl[f])
			lc = label.cellcount() if label else -2
			usage = abs(cells) + lc + 2
			yield (position, cells, lc)

			indents, r = divmod(usage, alignment)
			position += (indents * alignment)
			if r != 0:
				position += alignment

		yield (position, 0, 0)

	def connect(self, title):
		"""
		# Connect the monitor to a new conceptual data source.
		"""
		self._last = self._offset = sysclock.elapsed()
		self._image = {}
		self.prefix(())
		self.suffix(())
		self._positions = self._calculate_fields()

	def _update(self, discrete, continuous):
		ntime = sysclock.elapsed()
		dt = ntime.decrease(self._last)
		self._last = ntime
		d['time'].append(dt)

	def update(self, fields):
		"""
		# Update the field values of the monitor's image.
		"""
		self._image.update(fields)

	def prefix(self, *words):
		"""
		# Attach a constant phrase to the beginning of the monitor.
		"""
		self._prefix = matrix.Context.Phrase.from_words(*words)

	def suffix(self, *words):
		"""
		# Attach a constant phrase to the end of the monitor.
		"""
		self._suffix = matrix.Context.Phrase.from_words(*words)

	def render(self):
		theme = self.theme
		layout = self.layout

		for (k, fpad), (position, cells, lc) in zip(layout.fields(), self._positions):
			value = theme.render(k, self._image[k])
			lstr = layout.labels[k]
			label = lstr and theme.render('Label', lstr) or None
			yield label, value, position, (cells - value.cellcount())

	def phrase(self) -> matrix.Context.Phrase:
		"""
		# The monitor's image as a single phrase instance.
		"""
		phrases = [x for x in self.render() if x[0] is not None]
		labels = (x[0] for x in phrases)
		values = (x[1] for x in phrases)

		n = (lambda x: self.theme.render('Label', x))
		sep = (n(': '))
		lseps = (sep for i in range(len(phrases)))
		fseps = map(n, self.layout.separators(len(phrases)))

		return tools.interlace(labels, lseps, values, fseps)

	def snapshot(self, encoding='utf-8') -> bytes:
		"""
		# A bytes form of the &Monitor.phrase. (The image without cursor movement)
		"""
		l = list(self.phrase())
		cells = sum(x.cellcount() for x in l)
		rph = map(self.context.render, l)
		return cells, b''.join(itertools.chain.from_iterable(rph)).decode('utf-8')

class Control(object):
	"""
	# Root monitor control; manages the device interface, screen, and status context.
	"""

	def __init__(self, device, screen, context):
		self.device = device
		self.screen = screen
		self.context = context

		self._buffer = []
		self._io = io.FileIO(device.fileno(), closefd=False, mode='w')
		self._write = self._io.write

	def allocate(self, point, width=None, height=1) -> matrix.Context:
		"""
		# Create a &matrix.Context instance relative to the &Control' status context.
		"""
		rctx = self.context
		if width is not None:
			width = rctx.width
		if height is not None:
			height = rctx.height

		top, left = point
		actx = self.context.__class__(rctx.terminal_type)
		actx.context_set_position((rctx.point[0]+top, rctx.point[1]+left))
		actx.context_set_dimensions((width, height))
		return actx

	def reflect(self, monitor):
		"""
		# Render and emit the changes that occurred.

		# Operation is buffered and must flushed to be effective.
		"""

		if not monitor._prefix:
			offset = 0
		else:
			offset = monitor._prefix.cellcount() + 2

			i = itertools.chain.from_iterable([
				(monitor.context.seek((0, 0)),),
				monitor.context.render(monitor._prefix),
			])
			self._buffer.append(b''.join(i))
			self._buffer.append(monitor.context.reset_text())

		for label, ph, position, pad in monitor.render():
			if pad > 0:
				i = itertools.chain.from_iterable([
					(monitor.context.seek((position+offset, 0)), b' ' * pad),
					monitor.context.render(ph),
					(b' ',),
					monitor.context.render(label) if label else (),
				])
				self._buffer.append(b''.join(i))
			else:
				if label is None:
					i = itertools.chain.from_iterable([
						(monitor.context.seek((position+offset, 0)),),
						monitor.context.render(ph),
						(b':',),
					])
				else:
					i = itertools.chain.from_iterable([
						(monitor.context.seek((position+offset, 0)),),
						monitor.context.render(label) if label else (),
						(b': ',),
						monitor.context.render(ph),
					])
				self._buffer.append(b''.join(i))

		self._buffer.append(monitor.context.reset_text())

		if monitor._suffix:
			i = itertools.chain.from_iterable([
				monitor.context.render(monitor._suffix),
			])
			self._buffer.append(b''.join(i))
			self._buffer.append(monitor.context.reset_text())

	def flush(self):
		"""
		# Write any buffered terminal changes to the device.
		"""
		l = len(self._buffer)
		buf = bytearray()
		buf += self.screen.exit_scrolling_region()
		for x in itertools.islice(self._buffer, 0, l):
			buf += x
		buf += self.screen.enter_scrolling_region()

		try:
			self._write(buf)
		except:
			raise
		else:
			del self._buffer[:l]

	def clear(self, monitor):
		"""
		# Clear the area used by the monitor's context.

		# Operation is buffered and must flushed to be effective.
		"""
		self._buffer.append(monitor.context.clear())

def setup(lines:int, atexit=b'', type='prepared',
		destruct=True,
		Context=matrix.Context,
	) -> Control:
	"""
	# Initialize the terminal for use with a scrolling region.

	# The given &lines determines the horizontal area allocation to
	# manage at the bottom or top of the screen. If negative,
	# the top of the screen will be allocated. Allocating both is
	# not supported by this interface as &Control only manages one
	# &matrix.Context.
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
	ctl = Control(device, screen, ctx)
	ctl._write(init)
	return ctl

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
