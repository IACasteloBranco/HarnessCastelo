import codecs
from dataclasses import dataclass, field

from backend.store import StreamEvent


@dataclass
class EventStreamDecoder:
    _decoder: codecs.IncrementalDecoder = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")("replace")
    )
    _buffer: list[str] = field(default_factory=list)
    _event_type: str = ""
    _data: list[str] = field(default_factory=list)
    _ordinal: int = 0
    _skip_lf: bool = False

    def feed(self, chunk: bytes) -> list[StreamEvent]:
        text = self._decoder.decode(chunk)
        if self._skip_lf:
            text = text.removeprefix("\n")
            self._skip_lf = False
        return self._drain_lines(text)

    def finish(self) -> list[StreamEvent]:
        events = self._drain_lines(self._decoder.decode(b"", final=True))
        if self._buffer:
            self._line("".join(self._buffer))
            self._buffer.clear()
        event = self._dispatch(complete=False)
        if event:
            events.append(event)
        return events

    def _drain_lines(self, text: str) -> list[StreamEvent]:
        events = []
        start = 0
        while True:
            endings = [index for index in (text.find("\r", start), text.find("\n", start)) if index >= 0]
            if not endings:
                break
            index = min(endings)
            ending = text[index]
            width = 2 if text[index:index + 2] == "\r\n" else 1
            self._skip_lf = ending == "\r" and width == 1 and index + 1 == len(text)
            self._buffer.append(text[start:index])
            line = "".join(self._buffer)
            self._buffer.clear()
            event = self._line(line.removesuffix("\r"))
            if event:
                events.append(event)
            start = index + width
        if start < len(text):
            self._buffer.append(text[start:])
        return events

    def _line(self, line: str) -> StreamEvent | None:
        if not line:
            return self._dispatch()
        if line.startswith(":"):
            return None
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "event":
            self._event_type = value
        elif field == "data":
            self._data.append(value)
        return None

    def _dispatch(self, complete: bool = True) -> StreamEvent | None:
        if not self._data and not self._event_type:
            return None
        event = StreamEvent(
            ordinal=self._ordinal,
            event_type=self._event_type or "message",
            data="\n".join(self._data),
            complete=complete,
        )
        self._ordinal += 1
        self._event_type = ""
        self._data.clear()
        return event
