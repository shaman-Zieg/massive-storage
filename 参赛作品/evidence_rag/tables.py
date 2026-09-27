"""Lossless cell values and bounded row views for long HTML tables.

Row/column positions are source coordinates, not inferred semantic labels.
The original table remains authoritative and is retained in the corpus.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], [], None
        self.in_table = 0
        self.row_open = False
        self.table_ends = []

    @staticmethod
    def span(value):
        try:
            return min(128, max(1, int(value)))
        except (ValueError, TypeError):
            return 1

    def end_cell(self):
        if self.cell is not None:
            text = re.sub(r"\s+", " ", "".join(self.cell[0])).strip()
            self.row.append((text, self.cell[1], self.cell[2]))
            self.cell = None

    def end_row(self):
        self.end_cell()
        if self.row or self.row_open:
            self.rows.append(self.row)
            self.row = []
        self.row_open = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table += 1
        elif self.in_table == 1:
            if tag == "tr":
                self.end_row()
                self.row_open = True
            elif tag in ("td", "th"):
                self.end_cell()
                options = dict(attrs)
                self.cell = ([], self.span(options.get("rowspan")), self.span(options.get("colspan")))
            elif self.cell is not None and tag in ("br", "p", "div"):
                self.cell[0].append(" ")

    def handle_endtag(self, tag):
        if self.in_table == 1:
            if tag in ("td", "th"):
                self.end_cell()
            elif tag in ("tr", "table"):
                self.end_row()
                if tag == 'table':
                    self.table_ends.append(len(self.rows))
        if tag == "table":
            self.in_table = max(0, self.in_table-1)

    def handle_data(self, data):
        if self.cell is not None:
            self.cell[0].append(data)


def table_rows(text):
    parser = _TableParser()
    parser.feed(text)
    parser.end_row()
    grid, max_col = {}, 0
    for r, row in enumerate(parser.rows[:5000]):
        table_end = next((end for end in parser.table_ends if end>r),len(parser.rows))
        col = 0
        for value, rowspan, colspan in row:
            while (r, col) in grid:
                col += 1
            if col >= 128:
                break
            for rr in range(r, min(r+rowspan, table_end,5000)):
                for cc in range(col, min(128,col+colspan)):
                    grid[rr,cc] = value
                    max_col = max(max_col,cc+1)
            col += colspan
    return [[grid.get((r,col),"") for col in range(max_col)] for r in range(min(5000,len(parser.rows)))]


class TableView:
    def __init__(self, text):
        self.rows = table_rows(text)
        self.caption = re.sub(r"<table\b.*", "", text, flags=re.S|re.I).strip()
        self.lines = [f"row {i+1}: "+" | ".join(f"C{j+1}: {v}" for j,v in enumerate(row))
                      for i,row in enumerate(self.rows)]

    def fragments(self):
        if not self.rows:
            return []
        leading = "\n".join(self.lines[:2])
        return [f"{self.caption}\n{leading}\n"+"\n".join(self.lines[max(0,i-1):i+2])
                for i in range(len(self.rows))]

    def select(self, question, budget=4500):
        from .index import tokens
        if not self.rows:
            return ""
        query = set(tokens(question))
        scores = [(len(query & set(tokens(line))), i) for i,line in enumerate(self.lines)]
        matches = [i for score,i in sorted(scores,key=lambda x:(-x[0],x[1])) if score>0]
        heading = (self.caption[:min(400,budget//5)]+"\n" if self.caption else "")
        heading += "Original table cells; merged cells repeated.\n"
        suffix = '\n[Omitted rows/cell text require the original image.]'
        available = max(0,budget-len(heading)-len(suffix))
        selected = {}
        def excerpt(line,limit):
            if len(line)<=limit:
                return line
            # Mark every clipping operation; never infer missing cells/headers.
            position = min((line.lower().find(term) for term in query
                            if len(term)>2 and term in line.lower()),default=0)
            start=max(0,position-limit//3)
            prefix=line.split(':',1)[0]+': [...] '
            return (prefix+line[start:start+max(0,limit-len(prefix)-6)]+' [...]')[:limit]
        order=list(dict.fromkeys(matches[:1]+list(range(min(2,len(self.rows))))+matches[:8]))
        for i in order:
            if available<35:
                break
            # One enormous first row must not crowd out the matched late row.
            limit=min(available, max(80,available//2)) if len(order)>1 else available
            line=excerpt(self.lines[i],limit)
            selected[i]=line
            available-=len(line)+1
        nearby=[j for i in list(selected) for j in (i-1,i+1) if 0<=j<len(self.rows)]
        for i in list(dict.fromkeys(nearby+list(range(min(8,len(self.rows)))))):
            if i not in selected and len(self.lines[i])+1<=available:
                selected[i]=self.lines[i];available-=len(self.lines[i])+1
        omitted=len(selected)<len(self.rows) or any(v!=self.lines[i] for i,v in selected.items())
        return (heading+'\n'.join(selected[i] for i in sorted(selected))+(suffix if omitted else ''))[:budget]
