# --------------------------------------------------------------------
# ▼▼▼ ここから追加（最小変更）：GoodNotes用CSVユーティリティ＋ボタン ▼▼▼

def _gn_clean(s: str) -> str:
    if s is None:
        return ""
    return str(s).replace("\ufeff", "").strip().replace("　", "")

def _gn_normalize_newlines(text: str, newline: str = "\n") -> str:
    """セル内の改行をLFに統一（必要なら CRLF へ再変換）"""
    if text is None:
        return ""
    t = re.sub(r"\r\n|\r", "\n", str(text))
    if newline == "\r\n":
        t = t.replace("\n", "\r\n")
    return t

def _gn_make_front_back(row: pd.Series,
                        numbering: str = "ABC",
                        add_labels: bool = True,
                        add_meta: bool = False) -> tuple[str, str]:
    q = _gn_clean(row.get("問題文", ""))

    choices = [
        _gn_clean(row.get("選択肢1", "")),
        _gn_clean(row.get("選択肢2", "")),
        _gn_clean(row.get("選択肢3", "")),
        _gn_clean(row.get("選択肢4", "")),
        _gn_clean(row.get("選択肢5", "")),
    ]
    labels = ["A","B","C","D","E"] if numbering == "ABC" else ["1","2","3","4","5"]
    choice_lines = [f"{labels[i]}. {_gn_normalize_newlines(txt)}" for i, txt in enumerate(choices) if txt]

    front = _gn_normalize_newlines(q)
    if choice_lines:
        front = front + "\n\n" + "\n".join(choice_lines)

    ans = _gn_clean(row.get("正解", ""))
    back = f"正解: {ans}" if add_labels else ans

    if add_meta:
        subject = _gn_clean(row.get("科目分類",""))
        link = _gn_clean(row.get("リンクURL",""))
        extra = "\n".join([s for s in (subject, link) if s])
        if extra:
            back = back + "\n\n" + _gn_normalize_newlines(extra)

    back = _gn_normalize_newlines(back)
    return front, back

def dataframe_to_goodnotes_bytes(df: pd.DataFrame,
                                 numbering: str = "ABC",
                                 add_labels: bool = True,
                                 add_meta: bool = False,
                                 overall_line_ending: str = "lf",
                                 quote_all: bool = False) -> bytes:
    """
    任意の DataFrame から GoodNotes 用 Front/Back CSV を UTF-8(BOM付き) bytes で返す。
    - セル内部の改行は LF に正規化（GoodNotesでの表示安定のため）
    - ファイル全体の改行は overall_line_ending で 'lf' or 'crlf'
    """
    base = ensure_output_columns(df)

    fronts, backs = [], []
    for _, row in base.iterrows():
        f, b = _gn_make_front_back(row, numbering=numbering, add_labels=add_labels, add_meta=add_meta)
        fronts.append(f); backs.append(b)

    out = pd.DataFrame({"Front": fronts, "Back": backs})

    for c in out.columns:
        out[c] = out[c].map(lambda v: _gn_normalize_newlines(v, "\n"))

    file_nl = "\n" if overall_line_ending.lower() == "lf" else "\r\n"
    import csv as _csv

    buf = io.StringIO()
    buf.write("\ufeff")
    out.to_csv(
        buf,
        index=False,
        lineterminator=file_nl,
        quoting=_csv.QUOTE_ALL if quote_all else _csv.QUOTE_MINIMAL,
        doublequote=True,
        escapechar="\\",
    )
    return buf.getvalue().encode("utf-8")

st.download_button(
    label="📥 GoodNotes用CSV（Front/Back）をダウンロード",
    data=dataframe_to_goodnotes_bytes(
        df_filtered,
        numbering="ABC",
        add_labels=True,
        add_meta=False,
        overall_line_ending="lf",
    ),
    file_name=f"{file_prefix}_goodnotes.csv",
    mime="text/csv",
)
# --------------------------------------------------------------------
