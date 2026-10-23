import codecs
from dataclasses import dataclass, field

from store import StreamEvent


@dataclass
class EventStreamDecoder:
    _decoder: codecs.IncrementalDecoder = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")("replace")
    )
    _buffer: str = ""
    _event_type: str = ""
    _data: list[str] = field(default_factory=list)
    _ordinal: int = 0

    def feed(self, chunk: bytes) -> list[StreamEvent]:
        self._buffer += self._decoder.decode(chunk)
        return self._drain_lines()

    def finish(self) -> list[StreamEvent]:
        self._buffer += self._decoder.decode(b"", final=True)
        events = self._drain_lines()
        if self._buffer:
            self._line(self._buffer.removesuffix("\r"))
            self._buffer = ""
        event = self._dispatch(complete=False)
        if event:
            events.append(event)
        return events

    def _drain_lines(self) -> list[StreamEvent]:
        events = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            event = self._line(line.removesuffix("\r"))
            if event:
                events.append(event)
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
