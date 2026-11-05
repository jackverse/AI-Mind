# -*- coding: utf-8 -*-
"""刷题页：抽题 → 作答 → 判分 → 写入 review.json（与 CLI 进度互通）。"""
import random
import tkinter as tk
from tkinter import ttk

import ui
from core import store

MODES = [("全部题目", "all"), ("错题本", "wrong"), ("到期复习", "due")]


class QuizPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self.items = []          # [(subject, question)]
        self.reviews = {}
        self.idx = 0
        self.right = 0
        self.answered = False
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        bar = tk.Frame(self, bg=ui.C["bg"])
        bar.pack(fill="x", padx=24, pady=(20, 8))
        tk.Label(bar, text="刷题", font=(ui.UI, 18, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")

        self.subject = tk.StringVar()
        self.mode = tk.StringVar(value=MODES[0][0])
        self.amount = tk.StringVar(value="5")
        self.chapter = tk.StringVar()

        box = tk.Frame(bar, bg=ui.C["bg"])
        box.pack(side="right")

        def kv(label, widget):
            tk.Label(box, text=label, font=ui.F["small"], bg=ui.C["bg"],
                     fg=ui.C["muted"]).pack(side="left", padx=(12, 4))
            widget.pack(side="left")

        self.cb_subject = ttk.Combobox(box, textvariable=self.subject, width=13,
                                       state="readonly")
        kv("科目", self.cb_subject)
        self.cb_mode = ttk.Combobox(box, textvariable=self.mode, width=9,
                                    state="readonly", values=[m[0] for m in MODES])
        kv("模式", self.cb_mode)
        kv("题量", ttk.Spinbox(box, from_=1, to=50, width=3, textvariable=self.amount))
        kv("章节", ttk.Entry(box, textvariable=self.chapter, width=10))
        ttk.Button(box, text="开始", style="Accent.TButton",
                   command=self.start).pack(side="left", padx=(14, 0))

        self.body = tk.Frame(self, bg=ui.C["bg"])
        self.body.pack(fill="both", expand=True, padx=24, pady=(4, 20))

        self.card = tk.Frame(self.body, bg=ui.C["card"], highlightthickness=1,
                             highlightbackground=ui.C["line"])
        self.card.pack(fill="x", anchor="n")
        self.inner = tk.Frame(self.card, bg=ui.C["card"])
        self.inner.pack(fill="both", expand=True, padx=28, pady=22)

        self.progress = tk.Label(self.inner, text="", font=ui.F["small"],
                                 bg=ui.C["card"], fg=ui.C["muted"], anchor="w")
        self.progress.pack(fill="x")
        self.chapter_lbl = tk.Label(self.inner, text="", font=ui.F["small"],
                                    bg=ui.C["card"], fg=ui.C["accent"], anchor="w")
        self.chapter_lbl.pack(fill="x", pady=(2, 8))

        self.q_lbl = tk.Label(self.inner, text="选好科目和题量后点「开始」", font=(ui.UI, 12),
                              bg=ui.C["card"], fg=ui.C["text"], justify="left",
                              anchor="w", wraplength=760)
        self.q_lbl.pack(fill="x", pady=(0, 14))

        self.opt_box = tk.Frame(self.inner, bg=ui.C["card"])
        self.opt_box.pack(fill="x")
        self.opts = []
        for i in range(4):
            b = tk.Button(self.opt_box, text="", anchor="w", justify="left",
                          font=ui.F["body"], bg="#f6f8fc", fg=ui.C["text"],
                          activebackground="#e6eeff", relief="flat", bd=0,
                          padx=14, pady=10, cursor="hand2", wraplength=700,
                          command=lambda i=i: self._answer(i))
            b.pack(fill="x", pady=4)
            self.opts.append(b)

        self.feedback = tk.Label(self.inner, text="", font=(ui.UI, 10, "bold"),
                                 bg=ui.C["card"], anchor="w", justify="left",
                                 wraplength=760)
        self.feedback.pack(fill="x", pady=(12, 2))
        self.analysis = tk.Label(self.inner, text="", font=ui.F["small"],
                                 bg=ui.C["card"], fg=ui.C["muted"], anchor="w",
                                 justify="left", wraplength=760)
        self.analysis.pack(fill="x")

        self.next_btn = tk.Button(self.inner, text="下一题", font=ui.F["body"],
                                  bg=ui.C["accent"], fg="white", relief="flat",
                                  padx=18, pady=7, cursor="hand2",
                                  command=self._next)
        self.next_btn.pack(anchor="e", pady=(14, 0))
        self.next_btn.pack_forget()

        self.inner.bind("<Configure>", self._on_resize)

    def _on_resize(self, e):
        w = max(360, e.width - 120)
        self.q_lbl.configure(wraplength=w)
        self.feedback.configure(wraplength=w)
        self.analysis.configure(wraplength=w)
        for b in self.opts:
            b.configure(wraplength=w - 60)

    # ------------------------------------------------------------------ 逻辑
    def start(self, **_):
        subjects = self.ctx.subjects()
        if not self.cb_subject.get():
            self.cb_subject.configure(values=["全部科目"] + subjects)
            self.cb_subject.set("全部科目" if subjects else "")
        target = self.cb_subject.get()
        chosen = subjects if target in ("", "全部科目") else [target]
        mode = dict(MODES).get(self.mode.get(), "all")
        chapter = self.chapter.get().strip() or None

        pool = []
        for s in chosen:
            for q in store.pick_pool(self.ctx.kb, s, mode=mode, chapter=chapter):
                pool.append((s, q))
        if not pool:
            self._empty("没有符合条件的题目：换个科目、清空章节，或先去练几题攒错题。")
            return
        random.shuffle(pool)
        try:
            n = max(1, int(self.amount.get()))
        except ValueError:
            n = 5
        self.items = pool[:n]
        self.reviews = {s: store.load_review(self.ctx.kb, s) for s in chosen}
        self.idx = 0
        self.right = 0
        self._render()

    def _empty(self, msg):
        self.items = []
        self.q_lbl.configure(text=msg, font=(ui.UI, 11))
        self.chapter_lbl.configure(text="")
        self.progress.configure(text="")
        for b in self.opts:
            b.pack_forget()
        self.feedback.configure(text="")
        self.analysis.configure(text="")
        self.next_btn.pack_forget()

    def _render(self):
        if self.idx >= len(self.items):
            self._finish()
            return
        subject, q = self.items[self.idx]
        self.answered = False
        self.q_lbl.configure(text=q.get("q", ""), font=(ui.UI, 12))
        self.chapter_lbl.configure(text=f"{q.get('chapter', '')}   ·   {subject}")
        self.progress.configure(text=f"第 {self.idx + 1} / {len(self.items)} 题")
        self.feedback.configure(text="")
        self.analysis.configure(text="")
        self.next_btn.pack_forget()
        opts = q.get("options") or {}
        for i, b in enumerate(self.opts):
            key = "ABCD"[i]
            text = opts.get(key)
            if text:
                b.configure(text=f"{key}.  {text}", state="normal", bg="#f6f8fc",
                            fg=ui.C["text"])
                b.pack(fill="x", pady=4)
            else:
                b.configure(text="", state="disabled")
                b.pack_forget()

    def _answer(self, i):
        if self.answered or not self.items:
            return
        subject, q = self.items[self.idx]
        picked = "ABCD"[i]
        answer = str(q.get("answer", "")).upper()
        ok = picked == answer
        self.answered = True
        self.right += 1 if ok else 0

        for j, b in enumerate(self.opts):
            k = "ABCD"[j]
            if k == answer:
                b.configure(bg="#d7f2e1", fg=ui.C["ok"])
            elif k == picked:
                b.configure(bg="#fbe0e0", fg=ui.C["bad"])
            b.configure(state="disabled")

        self.feedback.configure(
            text=("√ 答对" if ok else f"× 答错，正确答案是 {answer}"),
            fg=ui.C["ok"] if ok else ui.C["bad"])
        if q.get("analysis"):
            self.analysis.configure(text="解析：" + q["analysis"])

        review = self.reviews.setdefault(subject, {})
        store.apply_answer(review, q.get("id"), ok)
        try:
            store.save_review(self.ctx.kb, subject, review)
        except OSError as e:
            self.analysis.configure(text=f"进度保存失败：{e}")
        self.next_btn.pack(anchor="e", pady=(14, 0))

    def _next(self):
        self.idx += 1
        self._render()

    def _finish(self):
        total = len(self.items)
        rate = int(self.right * 100 / total) if total else 0
        self.q_lbl.configure(text=f"本组结束：{total} 题，答对 {self.right}，正确率 {rate}%",
                             font=(ui.UI, 13, "bold"))
        self.chapter_lbl.configure(text="")
        self.progress.configure(text="")
        for b in self.opts:
            b.pack_forget()
        self.feedback.configure(text="")
        self.analysis.configure(text="错题已进错题本，1 天后可在「错题本」页复习。")
        self.next_btn.pack_forget()

    # ------------------------------------------------------------------
    def on_show(self, subject=None, mode=None, **kw):
        subjects = self.ctx.subjects()
        self.cb_subject.configure(values=["全部科目"] + subjects)
        if not self.cb_subject.get():
            self.cb_subject.set(subject or ("全部科目" if subjects else ""))
        elif subject:
            self.cb_subject.set(subject)
        if mode:
            for label, key in MODES:
                if key == mode:
                    self.mode.set(label)
        if kw.get("auto") and self.cb_subject.get():
            self.start()


def make(master, ctx, app):
    return QuizPage(master, ctx, app)
