"""Small urwid building blocks: list rows, bordered panes, the palette."""
from __future__ import annotations

import urwid

# (name, fg16, bg16, mono, fg256, bg256): one line per role covers every depth.
# Meaning never rides on colour alone: focus also gets bold/reverse, errors
# also start with "ERROR:", state is a word.
PALETTE = [
    # Mid-brightness colours (the plain, non-bright 16) contrast with both a
    # dark and a light background; bright yellow/green/red vanish on white.
    # Selection and the key bar use reverse video: the terminal's own
    # foreground and background swapped, readable in any theme.
    ("frame", "default", "default", "", "default", "default"),
    ("body", "default", "default", "", "default", "default"),
    ("frame_focus", "dark magenta,bold", "default", "bold", "#a0a,bold", "default"),
    # The focused pane's title: no colour can be read on every theme (dark
    # magenta is 1.9:1 on GNOME's dark background), reverse video always can.
    ("title_focus", "default,standout,bold", "default", "standout,bold",
     "default,standout,bold", "default"),
    ("sel_focus", "default,standout", "default", "standout", "default,standout", "default"),
    ("dim", "default", "default", "", "default", "default"),
    ("state", "dark green,bold", "default", "bold", "#080,bold", "default"),
    ("key", "default,standout", "default", "standout", "default,standout", "default"),
    ("msg", "default", "default", "", "default", "default"),
    ("error", "dark red,bold", "default", "bold", "#c00,bold", "default"),
    ("prompt", "dark magenta,bold", "default", "bold", "#a0a,bold", "default"),
]


class Row(urwid.Text):
    """A selectable one-line list row carrying the thing it stands for."""
    _selectable = True

    def __init__(self, text, value=None):
        super().__init__(text, wrap="clip")
        self.value = value

    def keypress(self, size, key):
        return key


def rows(items) -> list:
    """``items`` are ``(text, value)`` pairs."""
    return [urwid.AttrMap(Row(t, v), None, focus_map="sel_focus") for t, v in items]


class ListPane(urwid.ListBox):
    """A list whose rows can be replaced while keeping the cursor in place."""

    def __init__(self):
        super().__init__(urwid.SimpleFocusListWalker([]))

    def set_items(self, items, keep: bool = True) -> None:
        pos = self.focus_position if (keep and len(self.body)) else 0
        self.body[:] = rows(items)
        if len(self.body):
            self.focus_position = min(pos, len(self.body) - 1)

    def current(self):
        """The value of the row under the cursor, or None."""
        if not len(self.body):
            return None
        return self.focus.original_widget.value

    def select(self, value) -> None:
        for i, w in enumerate(self.body):
            if w.original_widget.value == value:
                self.focus_position = i
                return


class Pane(urwid.WidgetWrap):
    """A titled border around a body; the border shows focus."""

    def __init__(self, num: int, name: str, title: str, body, box: dict):
        self.num, self.name, self.title, self.body = num, name, title, body
        self.note = ""
        self.focused = False
        self.attr = urwid.AttrMap(urwid.Text(""), "frame")
        self.relabel(box)
        super().__init__(self.attr)

    def relabel(self, box: dict) -> None:
        self.box = box
        # The body is mapped to plain "body" first, so the focus colour on the
        # outer AttrMap reaches only the border, not the rows inside.
        self.attr.original_widget = urwid.LineBox(
            urwid.AttrMap(self.body, "body"), title=self.heading(), title_align="left",
            title_attr="title_focus" if self.focused else None, **box)

    def heading(self) -> str:
        # The focused pane is also marked in the title, for mono screens.
        mark = ">" if self.focused else ""
        note = f" ({self.note})" if self.note else ""
        return f"{mark}{self.num} {self.title}{note}"

    def set_focus(self, on: bool) -> None:
        if on != self.focused:
            self.focused = on
            self.relabel(self.box)  # title_attr is fixed when the LineBox is made
        self.attr.set_attr_map({None: "frame_focus" if on else "frame"})

    def set_note(self, note: str) -> None:
        self.note = note
        self.attr.original_widget.set_title(self.heading())


class Live(urwid.Text):
    """Text that recomputes itself from a callback at every render, so it is
    always current and fits the width it is given."""

    def __init__(self, make):
        super().__init__("", wrap="clip")
        self.make = make

    def render(self, size, focus=False):
        self.set_text(self.make(size[0]))
        return super().render(size, focus)

    def rows(self, size, focus=False):
        self.set_text(self.make(size[0]))
        return super().rows(size, focus)


class ClickRow(urwid.Text):
    """A line of ``(text, action)`` segments rebuilt at every render; a click
    on a segment with an action calls ``on_click(action)``. Selectable, so a
    click also focuses the pane it sits in."""
    _selectable = True

    def __init__(self, make, on_click):
        super().__init__("", wrap="clip")
        self.make, self.on_click, self.segments = make, on_click, []

    def _fill(self):
        self.segments = self.make()
        self.set_text([(("key" if a else "msg"), t) for t, a in self.segments] or "")

    def render(self, size, focus=False):
        self._fill()
        return super().render(size, focus)

    def rows(self, size, focus=False):
        self._fill()
        return super().rows(size, focus)

    def keypress(self, size, key):
        return key

    def mouse_event(self, size, event, button, col, row, focus):
        if event != "mouse press" or button != 1:
            return False
        x = 0
        for text, action in self.segments:
            if x <= col < x + len(text):
                if action:
                    self.on_click(action)
                return True
            x += len(text)
        return True
