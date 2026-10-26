"""Turn a model response into a downloadable document or spreadsheet."""

import csv
import io
import json
from copy import copy
from itertools import islice
from xml.sax.saxutils import escape

from openpyxl import Workbook, load_workbook
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


MIME = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


class InvalidArtifact(ValueError):
    pass


def _table(source: str) -> tuple[list[str], list[list[str]]]:
    source = source.strip()
    if source.startswith("```"):
        source = source.partition("\n")[2].rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(source)
    except json.JSONDecodeError as exc:
        raise InvalidArtifact("A IA não retornou uma tabela válida. Tente novamente.") from exc
    if not isinstance(payload, dict) or set(payload) != {"columns", "rows"}:
        raise InvalidArtifact("A IA não retornou colunas e linhas válidas.")
    columns, rows = payload["columns"], payload["rows"]
    if (not isinstance(columns, list) or not 1 <= len(columns) <= 50 or
            not all(isinstance(value, str) and value.strip() and len(value) <= 255 for value in columns) or
            not isinstance(rows, list) or len(rows) > 10_000):
        raise InvalidArtifact("A tabela excedeu os limites ou veio incompleta.")
    clean = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns) or any(
            value is not None and not isinstance(value, (str, int, float, bool)) for value in row
        ):
            raise InvalidArtifact("A IA retornou uma linha inválida.")
        clean.append(["" if value is None else str(value) for value in row])
    return columns, clean


def build_artifact(format: str, answer: str) -> bytes:
    if format == "pdf":
        if not answer.strip():
            raise InvalidArtifact("A resposta está vazia.")
        output = io.BytesIO()
        styles = getSampleStyleSheet()
        story = []
        for block in answer.split("\n\n"):
            text = escape(block.strip()).replace("\n", "<br/>")
            if text:
                story.extend((Paragraph(text, styles["BodyText"]), Spacer(1, 10)))
        SimpleDocTemplate(output, title="Maximus AI", pagesize=(595, 842),
                          leftMargin=48, rightMargin=48).build(story)
        data = output.getvalue()
    elif format in ("csv", "xlsx"):
        columns, rows = _table(answer)
        if format == "csv":
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerows([["'" + value if value.startswith(("=", "+", "-", "@")) else value
                              for value in row] for row in [columns, *rows]])
            data = ("\ufeff" + output.getvalue()).encode("utf-8")
        else:
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Dados"
            for row in [columns, *rows]:
                sheet.append(["'" + value if value.startswith(("=", "+", "-", "@")) else value for value in row])
            for cell in sheet[1]:
                font = copy(cell.font)
                font.bold = True
                cell.font = font
            output = io.BytesIO()
            workbook.save(output)
            data = output.getvalue()
    else:
        raise InvalidArtifact("Formato não suportado.")
    if len(data) > 20_000_000:
        raise InvalidArtifact("O arquivo gerado excedeu 20 MB.")
    return data


def preview_table(format: str, data: bytes) -> dict:
    workbook = None
    if format in ("csv", "tsv"):
        rows = csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter="\t" if format == "tsv" else ",")
    elif format == "xlsx":
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        rows = workbook.active.iter_rows(values_only=True)
    else:
        raise InvalidArtifact("Formato não suportado.")
    header = next(rows, ())
    preview = [["" if value is None else str(value) for value in row] for row in islice(rows, 101)]
    if workbook:
        workbook.close()
    return {"columns": ["" if value is None else str(value) for value in header],
            "rows": preview[:100], "truncated": len(preview) > 100}
