#!/usr/bin/env python3
"""Measure retrieval quality: recall and reciprocal rank over a fixed query set.

Retrieval degrades silently. Ten results still come back, and they are still
plausible, so a change that makes ranking worse has no symptom at all. This
script is the only thing in the repository that can see it happen: it builds a
synthetic corpus, runs a fixed set of queries with recorded judgements through
the shipped search, and reports what it found against a recorded baseline.

    python scripts/evaluate_retrieval.py
    python scripts/evaluate_retrieval.py --embedder deterministic   # offline control
    python scripts/evaluate_retrieval.py --record                   # move the baseline
    python scripts/evaluate_retrieval.py --corpus DIR --queries FILE

It is a script rather than a test because it needs the real embedder, and the
suite is required to run offline. It writes to a temporary directory and removes
it, and it prints the figures it measured rather than a verdict alone — a run
here is meant to be quotable evidence.

A figure measured with the deterministic embedder is not a quality figure. Those
vectors carry no meaning; such a run measures that the mechanism works and is
worth having for exactly one reason — a measurement that cannot move cannot
report a regression.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

SUMMARY = (__doc__ or "").split("\n")[0]

BASELINE_PATH = REPO / "docs" / "retrieval-baseline.json"

# Recall at these cut-offs, and reciprocal rank at the last of them. Fixed
# rather than derived from --limit so that two runs are always comparable.
RECALL_AT = (1, 5, 10)
MRR_AT = 10

# A run may drift by a hair between machines: ONNX kernels differ, and a tie
# broken the other way moves one query. Anything larger than this is a change in
# behaviour, not in arithmetic.
TOLERANCE = 0.005


# --- the evaluation set ----------------------------------------------------
#
# Invented material. No real case content ever enters this repository, and this
# corpus is written into a temporary directory at run time rather than committed
# as document files. The register is the fictional harbour lease used by the
# test fixtures and by `verify_model_paths.py`, so a reader recognises it.
#
# Three languages, because the shipped embedder is multilingual and a figure
# measured only in English says nothing about the corpus this workbench holds.
# Three documents answer nothing: without them recall is satisfied by a corpus
# in which everything is relevant.

DOCUMENTS: dict[str, str] = {
    "lease-draft-2020.md": """# Draft Harbour Lease (2020)

## Parties

This draft records the terms discussed with Westgate Freight for the harbour
lease. It was prepared by the clerk in November 2020 and circulated to the
board for comment. It is a draft and was never executed.

## Term and payment

The draft proposed a term of seven years from the first day of April 2021, with
an annual fee of thirty-six thousand payable each April. A review was proposed
after the third year rather than the fourth. The berth offered was berth two,
with no warehouse and no right to store cargo overnight.

## Status

The proposal was withdrawn before signature after Westgate Freight declined the
dredging obligation in clause nine. The clerk was instructed to open the matter
again in the new year. Nothing in this draft has any effect, and it is retained
only because the board asked for the negotiating history to be kept.
""",
    "lease-award-2021.md": """# Harbour Lease Award (2021)

## Award

The port authority board awarded the harbour lease to Northgate Holdings on
14 March 2021. The award covers berth four, the adjoining warehouse, and the
right to load and unload cargo between April and October in each year of the
term. It replaces the withdrawn proposal of the previous November.

## Term and payment

The term runs for nine years from the first day of April 2021, with a review
after the fourth year. An annual fee of forty-two thousand is payable each
January to the port authority. Late payment carries interest at four per cent
above the base rate, calculated daily from the date the sum fell due.

## Obligations

The lessee shall keep the berth clear of obstruction, shall not sublet without
consent in writing, and shall contribute one third of the cost of dredging the
outer channel when the harbourmaster certifies that dredging is required.

## Signatures

The award was signed by the chair of the board and by the company secretary.
A copy was filed with the registry on 19 March 2021 and a second copy was sent
to the harbourmaster's office in the same week.
""",
    "lease-amendment-2022.md": """# Amendment to the Harbour Lease (2022)

## Purpose

This amendment varies the harbour lease held by Northgate Holdings. It does not
replace the award and every term not varied here continues unchanged.

## Payment

The annual fee is raised to forty-eight thousand, payable from January 2023.
The increase reflects the cost of the channel works completed in the autumn.
The interest rate on late payment is unchanged.

## Additional berth

Berth five is added to the demise from the same date, together with the use of
the weighbridge on the east side. The lessee accepts the condition of berth five
as it stands and the authority gives no undertaking as to its depth.

## Execution

Signed on 8 December 2022 by the chair and by a director of the lessee, and
filed with the registry the following week.
""",
    "board-minutes-february.md": """# Board Minutes, 2 February 2021

Present: the chair, the harbourmaster, and four members of the board. The
secretary recorded the meeting. Apologies were received from one member.

## Channel works

The board discussed the dredging contracts for the outer channel. The
harbourmaster reported that silt at the entrance had reduced the usable depth
by half a metre since the survey in November, and that two operators had
already complained in writing.

## Charges

The board deferred the tariff decision to the next meeting. Two members asked
for the schedule to be circulated in advance, on the grounds that the last
revision had been taken without sight of the figures.

## Any other business

The clerk reported that the lease negotiation reopened in January was
progressing and that a recommendation would come to the March meeting.
""",
    "board-minutes-march.md": """# Board Minutes, 12 March 2021

Present: the chair, the harbourmaster, and five members of the board.

## The lease

The board approved the award of the harbour lease to Northgate Holdings on the
terms circulated with the agenda. Two members recorded an objection to the
approval, on the grounds that the berth had not been advertised a second time
after the earlier proposal fell away.

## Tariffs

The tariff schedule deferred in February was adopted without amendment. The
harbourmaster undertook to publish it before the start of the season.

## Dredging

The contract for the outer channel was awarded to the lower of the two tenders.
The work is to begin after the end of the season and to finish before April.
""",
    "tariff-schedule.md": """# Tariff Schedule

## Mooring

Mooring is charged per metre of vessel length per day, counted from the moment a
line is made fast until the moment the last line is released. A vessel over
eighty metres pays a surcharge of one fifth.

## Storage

Storage in the warehouse is charged by the pallet by the week, with any part of
a week counted as a whole one. The first week is free for cargo landed under the
harbour lease. Dangerous goods are not accepted at any price.

## Waiver

The harbourmaster may waive a charge where weather closed the entrance for more
than a working day, and must record the reason in writing in the register kept
for that purpose.
""",
    "kitchen-notes.txt": """Unrelated kitchen notes about baking bread and grinding coffee.
The oven runs hot on the left side, so turn the tray after twenty minutes.
Buy more flour, and a new sieve if the old one has gone rusty.
The dough needs a longer rest in cold weather, closer to two hours than one.
""",
    "proekt-orendy-2020.md": """# Проєкт договору оренди (2020)

## Сторони

Проєкт фіксує умови, обговорені з компанією «Вестгейт» щодо оренди гавані.
Підготовлений секретарем у листопаді 2020 року та розісланий правлінню для
зауважень. Це проєкт, і його не підписували.

## Строк і платіж

Проєкт передбачав строк сім років від першого квітня 2021 року та щорічний
платіж у розмірі тридцяти шести тисяч, що сплачується у квітні. Перегляд
пропонувався після третього року. Пропонувався причал номер два, без складу.

## Стан

Пропозицію відкликано до підписання після того, як «Вестгейт» відмовився від
обов'язку щодо днопоглиблення. Секретарю доручено повернутися до питання у
новому році. Документ зберігається лише як частина історії перемовин.
""",
    "akt-orendy-2021.md": """# Акт передання оренди (2021)

## Передання

Правління порту передало оренду гавані компанії «Нортгейт» 14 березня 2021
року. Передання охоплює причал номер чотири, сусідній склад та право
навантажувати і розвантажувати вантаж з квітня до жовтня кожного року строку.

## Строк і платіж

Строк становить дев'ять років від першого квітня 2021 року з переглядом після
четвертого року. Щорічний платіж у розмірі сорока двох тисяч сплачується у
січні. За прострочення нараховуються відсотки — чотири над базовою ставкою.

## Обов'язки

Орендар зобов'язаний тримати причал вільним від перешкод, не передавати його в
суборенду без письмової згоди та сплачувати третину вартості днопоглиблення
зовнішнього каналу, коли капітан порту засвідчить потребу в роботах.

## Підписи

Документ підписали голова правління та секретар товариства. Копію передано до
реєстру 19 березня 2021 року.
""",
    "protokol-pravlinnya.md": """# Протокол засідання правління, 2 лютого 2021

Присутні: голова, капітан порту та четверо членів правління.

## Роботи на каналі

Правління обговорило контракти на днопоглиблення зовнішнього каналу. Капітан
порту повідомив, що намул біля входу зменшив придатну глибину на пів метра з
часу листопадового обстеження і що двоє операторів уже надіслали скарги.

## Збори

Правління відклало рішення щодо тарифів до наступного засідання. Двоє членів
попросили надіслати розклад заздалегідь, бо попередній перегляд ухвалили без
цифр перед очима.

## Інше

Секретар повідомив, що перемовини про оренду, відновлені у січні, тривають і
що рекомендація надійде на березневе засідання.
""",
    "pohoda.txt": """Журнал погоди. Понеділок: ясно, вітер слабкий, температура вісім градусів.
Вівторок: дощ уранці, потім прояснення. Середа: туман до полудня.
Четвер: сухо і холодно. П'ятниця: сильний вітер увечері, хвиля на вході.
Субота: мряка. Неділя: ясно, приморозок уночі, вдень до десяти градусів.
""",
    "dogovor-arendy-2021.md": """# Договор аренды (2021)

## Передача

Совет порта передал аренду гавани компании «Нортгейт» 14 марта 2021 года.
Договор охватывает причал номер четыре, склад рядом с ним и право грузить и
разгружать товар с апреля по октябрь каждого года срока.

## Срок и платёж

Срок составляет девять лет с первого апреля 2021 года, с пересмотром после
четвёртого года. Ежегодный платёж в размере сорока двух тысяч вносится в
январе. За просрочку начисляются проценты — четыре над базовой ставкой.

## Обязанности

Арендатор обязан держать причал свободным от помех, не сдавать его в
субаренду без письменного согласия и оплачивать треть стоимости
дноуглубления внешнего канала, когда капитан порта подтвердит необходимость.

## Подписи

Документ подписали председатель совета и секретарь общества. Копия направлена
в реестр 19 марта 2021 года.
""",
    "dopolnenie-2022.md": """# Дополнение к договору аренды (2022)

## Назначение

Дополнение изменяет договор аренды, заключённый с компанией «Нортгейт». Оно не
заменяет договор, и все условия, не изменённые здесь, продолжают действовать.

## Платёж

Ежегодный платёж повышается до сорока восьми тысяч и вносится с января 2023
года. Повышение отражает стоимость работ на канале, законченных осенью.
Ставка процентов за просрочку не меняется.

## Дополнительный причал

Причал номер пять добавляется с той же даты вместе с правом пользоваться
весовой на восточной стороне. Арендатор принимает состояние причала пять как
есть, и порт не даёт заверений о его глубине.

## Подписание

Подписано 8 декабря 2022 года председателем и директором арендатора, копия
направлена в реестр на следующей неделе.
""",
    "sluzhebnaya-zapiska.md": """# Служебная записка

## Состояние техники

Начальник смены сообщает, что кран номер два требует замены троса до конца
месяца. Работа крана ограничена половиной нагрузки, пока замена не выполнена.
Вторая смена подтверждает износ на том же участке троса.

## Просьба

Прошу выделить средства и согласовать остановку на два дня. Вторая смена
готова принять работу на себя, если остановку назначить на середину недели.
""",
    "kofe-zametki.txt": """Заметки о кофе. Зерно средней обжарки, помол крупнее обычного.
Вода девяносто два градуса, время пролива три минуты.
Купить новый фильтр и весы, старые врут на полграмма.
Молоко греть не выше шестидесяти, иначе вкус становится плоским.
""",
}


@dataclass(frozen=True)
class Judgement:
    """One query and the passage that answers it.

    Keyed to a filename and a phrase, never to a chunk id: chunk ids are minted
    afresh every time a document is rebuilt, so a judgement pinned to one
    measures nothing the second time it is run. A filename survives a reingest
    and a phrase survives a change of chunk size.
    """

    query: str
    language: str
    filename: str
    phrase: str
    # Other passages that answer the query just as well. Near-duplicate
    # documents are the ordinary case in a real corpus — a draft, the operative
    # version, an amendment — and several of them can carry the answer. A
    # judgement admitting only one would score a correct result as wrong, and
    # would punish exactly the component whose job is to choose between close
    # candidates.
    also: tuple[tuple[str, str], ...] = ()


# Three documents cover the lease in each language — a withdrawn draft, the
# operative award, and a later amendment — so a query about the fee or the term
# has three plausible answers and only one right one. That is what makes this a
# retrieval measurement rather than a topic-detection one.
JUDGEMENTS: tuple[Judgement, ...] = (
    Judgement(
        query="Which company holds the harbour lease?",
        language="en",
        filename="lease-award-2021.md",
        phrase="awarded the harbour lease to Northgate Holdings",
        # The amendment names the holder just as plainly. Measured, not assumed:
        # a reranker put that passage first, and it is not wrong to.
        also=(("lease-amendment-2022.md", "harbour lease held by Northgate Holdings"),),
    ),
    Judgement(
        query="What did the tenant pay each year before the increase?",
        language="en",
        filename="lease-award-2021.md",
        phrase="annual fee of forty-two thousand is payable each January",
    ),
    Judgement(
        query="From when is the higher rent due?",
        language="en",
        filename="lease-amendment-2022.md",
        phrase="raised to forty-eight thousand, payable from January 2023",
    ),
    Judgement(
        query="Which proposal was abandoned before anyone signed it?",
        language="en",
        filename="lease-draft-2020.md",
        phrase="withdrawn before signature",
    ),
    Judgement(
        query="Who disagreed when the board approved the award?",
        language="en",
        filename="board-minutes-march.md",
        phrase="Two members recorded an objection",
    ),
    Judgement(
        query="How is warehouse space charged?",
        language="en",
        filename="tariff-schedule.md",
        phrase="charged by the pallet by the week",
    ),
    Judgement(
        query="Who must pay part of the cost of clearing the channel?",
        language="en",
        filename="lease-award-2021.md",
        phrase="contribute one third of the cost of dredging",
    ),
    Judgement(
        query="Хто отримав право користуватися причалом?",
        language="uk",
        filename="akt-orendy-2021.md",
        phrase="передало оренду гавані компанії «Нортгейт»",
    ),
    Judgement(
        query="Яку пропозицію відкликали?",
        language="uk",
        filename="proekt-orendy-2020.md",
        phrase="відкликано до підписання",
    ),
    Judgement(
        query="Скільки років діє угода про оренду гавані?",
        language="uk",
        filename="akt-orendy-2021.md",
        phrase="Строк становить дев'ять років",
    ),
    Judgement(
        query="Що перенесли на потім?",
        language="uk",
        filename="protokol-pravlinnya.md",
        phrase="відклало рішення щодо тарифів",
    ),
    Judgement(
        query="Хто платить частину вартості робіт у каналі?",
        language="uk",
        filename="akt-orendy-2021.md",
        phrase="сплачувати третину вартості днопоглиблення",
    ),
    Judgement(
        query="Кто получил право пользоваться причалом?",
        language="ru",
        filename="dogovor-arendy-2021.md",
        phrase="передал аренду гавани компании «Нортгейт»",
        also=(("dopolnenie-2022.md", "договор аренды, заключённый с компанией «Нортгейт»"),),
    ),
    Judgement(
        query="С какого месяца действует новая сумма?",
        language="ru",
        filename="dopolnenie-2022.md",
        phrase="повышается до сорока восьми тысяч и вносится с января 2023",
    ),
    Judgement(
        query="На сколько лет заключено соглашение?",
        language="ru",
        filename="dogovor-arendy-2021.md",
        phrase="Срок составляет девять лет",
    ),
    Judgement(
        query="Какое оборудование нужно починить?",
        language="ru",
        filename="sluzhebnaya-zapiska.md",
        phrase="кран номер два требует замены троса",
    ),
    Judgement(
        query="Какой причал добавили к договору?",
        language="ru",
        filename="dopolnenie-2022.md",
        phrase="Причал номер пять добавляется",
    ),
)


# Enough to strip the grammar from a query so that "shares no content word with
# its answer" means what it says. Deliberately short: a long stopword list would
# make the disjointness claim easier to satisfy and therefore worth less.
STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        """a an and are as at be been by did do does for from had has have how in into is
        it its of on or over per that the this to under was were what when where which
        who whom will with""".split()
    ),
    "uk": frozenset(
        """а але б бо був була було були в для до за з за із й і коли кому кого хто що як
        який яка яке які на не о про при та то у це цей ця чи""".split()
    ),
    "ru": frozenset(
        """а бы был была было были в во для до его есть за и из или к как кто когда кого
        кому на не о об по при про с со то у что чем чья это этот эта эти""".split()
    ),
}

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def content_words(text: str, language: str) -> set[str]:
    """The words of `text` that carry meaning, lowercased."""
    stop = STOPWORDS.get(language, frozenset())
    return {w for w in (m.group(0).lower() for m in _WORD.finditer(text)) if w not in stop}


# --- metrics ---------------------------------------------------------------


def recall_at_k(relevance: Sequence[bool], k: int) -> float:
    """Whether a relevant passage appears in the first `k` results.

    One passage answers each query here, so this is a hit rate. It is called
    recall because that is what it measures when a query has one right answer,
    and saying "recall@1" of a set with one relevant item is unambiguous.
    """
    return 1.0 if any(relevance[:k]) else 0.0


def mrr_at_k(relevance: Sequence[bool], k: int) -> float:
    """One over the rank of the first relevant result, or zero if none is in `k`."""
    for index, hit in enumerate(relevance[:k], start=1):
        if hit:
            return 1.0 / index
    return 0.0


def aggregate(per_query: Sequence[Sequence[bool]]) -> dict[str, float]:
    """Mean of each metric over the queries."""
    if not per_query:
        return {f"recall@{k}": 0.0 for k in RECALL_AT} | {f"mrr@{MRR_AT}": 0.0}
    count = len(per_query)
    figures = {
        f"recall@{k}": sum(recall_at_k(r, k) for r in per_query) / count for k in RECALL_AT
    }
    figures[f"mrr@{MRR_AT}"] = sum(mrr_at_k(r, MRR_AT) for r in per_query) / count
    return figures


# --- measurement -----------------------------------------------------------


@dataclass
class Measurement:
    conditions: dict[str, Any]
    metrics: dict[str, dict[str, float]]
    by_language: dict[str, dict[str, float]]
    per_query: list[dict[str, Any]] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "recorded": date.today().isoformat(),
            # Platform and interpreter, because ONNX kernels differ between
            # them and a figure is only comparable against one produced the same
            # way. Deliberately not the hostname: this file is tracked in a
            # public repository.
            "measured_on": f"{platform.system()} {platform.machine()}, "
            f"python {platform.python_version()}",
            "conditions": self.conditions,
            "metrics": self.metrics,
            "by_language": self.by_language,
        }


def write_corpus(folder: Path, documents: Mapping[str, str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in documents.items():
        (folder / name).write_text(body, encoding="utf-8")


def is_relevant(judgement: Judgement, filename: str, text: str) -> bool:
    """Whether a returned passage answers the query.

    Both halves matter: the right document, and the part of it that carries the
    answer. A document-level judgement alone would be blind to which passage
    came back, which is exactly what the window and rerank legs change.
    """
    body = _normalise(text)
    for expected_file, expected_phrase in (
        (judgement.filename, judgement.phrase),
        *judgement.also,
    ):
        if filename == expected_file and _normalise(expected_phrase) in body:
            return True
    return False


def _normalise(text: str) -> str:
    """Collapse whitespace and case, so a phrase spanning a wrapped line matches."""
    return " ".join(text.lower().split())


def _leg_relevance(
    store: Any, chunk_ids: Sequence[str], judgement: Judgement
) -> list[bool]:
    chunks = store.get_chunks(list(chunk_ids))
    documents: dict[str, Any] = {}
    relevance: list[bool] = []
    for chunk_id in chunk_ids:
        chunk = chunks.get(chunk_id)
        if chunk is None:
            relevance.append(False)
            continue
        if chunk.document_id not in documents:
            documents[chunk.document_id] = store.get_document(chunk.document_id)
        document = documents[chunk.document_id]
        filename = document.filename if document is not None else ""
        relevance.append(is_relevant(judgement, filename, chunk.text))
    return relevance


def measure(
    context: Any,
    casefile_reference: str,
    judgements: Sequence[Judgement],
    *,
    limit: int,
    conditions: dict[str, Any],
) -> Measurement:
    """Run every query and score the fused ranking and each retriever alone.

    The fused ranking comes from the service layer's own search — this harness
    computes no ordering of its own. A harness with its own copy of the ranking
    rules measures that copy, and this project already forbids a second
    definition of a domain rule outside the service layer.

    The two legs are read straight off the store, which is reading rather than
    reimplementing: it is the only way to say whether a gain came from keyword
    or from vector retrieval.
    """
    casefile = context.casefiles.resolve(casefile_reference)
    legs: dict[str, list[list[bool]]] = {"keyword": [], "vector": [], "fused": []}
    languages: dict[str, list[list[bool]]] = {}
    per_query: list[dict[str, Any]] = []

    rankings: set[str] = set()
    for judgement in judgements:
        hits = context.search.search(casefile_reference, judgement.query, limit=limit)
        rankings.update(hit.ranking for hit in hits)
        fused = [
            is_relevant(judgement, hit.document.filename, hit.chunk.text) for hit in hits
        ]

        keyword_ids = context.store.search_keyword(casefile.id, judgement.query, limit)
        vector_ids = context.store.search_vector(
            casefile.id, context.embedder.embed_query(judgement.query), limit
        )
        keyword = _leg_relevance(context.store, keyword_ids, judgement)
        vector = _leg_relevance(context.store, vector_ids, judgement)

        legs["fused"].append(fused)
        legs["keyword"].append(keyword)
        legs["vector"].append(vector)
        languages.setdefault(judgement.language, []).append(fused)
        per_query.append(
            {
                "query": judgement.query,
                "language": judgement.language,
                "expects": judgement.filename,
                "rank": next((i for i, r in enumerate(fused, 1) if r), None),
                "keyword_rank": next((i for i, r in enumerate(keyword, 1) if r), None),
                "vector_rank": next((i for i, r in enumerate(vector, 1) if r), None),
            }
        )

    # What the search reported, not what the command line asked for. A reranker
    # that loads and then fails on every response would otherwise be recorded as
    # having produced these figures.
    conditions = dict(conditions)
    conditions["ranked_by"] = ", ".join(sorted(rankings)) if rankings else "no results"

    return Measurement(
        conditions=conditions,
        metrics={name: aggregate(rows) for name, rows in legs.items()},
        by_language={lang: aggregate(rows) for lang, rows in sorted(languages.items())},
        per_query=per_query,
    )


# --- baseline --------------------------------------------------------------


def compare(
    measured: Measurement, baseline: Mapping[str, Any], tolerance: float
) -> list[str]:
    """Metrics that fell below the baseline, named with the size of the fall."""
    fallen: list[str] = []
    recorded = baseline.get("metrics", {})
    for leg, figures in recorded.items():
        for metric, was in figures.items():
            now = measured.metrics.get(leg, {}).get(metric)
            if now is None:
                fallen.append(f"{leg} {metric}: not measured in this run (baseline {was:.3f})")
                continue
            if now < was - tolerance:
                fallen.append(f"{leg} {metric}: {now:.3f}, baseline {was:.3f} ({now - was:+.3f})")
    return fallen


def conditions_match(measured: Measurement, baseline: Mapping[str, Any]) -> list[str]:
    """Conditions that differ between this run and the recorded baseline.

    A figure is only comparable against one produced the same way. Comparing a
    real-embedder run against a stand-in baseline would report a regression that
    is nothing of the kind, or hide one that is.
    """
    recorded = baseline.get("conditions", {})
    differing = []
    # `queries` and `documents` are here because a smaller corpus with fewer
    # distractors is easier, so a run over one is not comparable with a baseline
    # recorded over the other however well the rest matches.
    for key in (
        "embedder",
        "reranker",
        "query_set",
        "chunk_max_chars",
        "window_max_chars",
        "limit",
        "queries",
        "documents",
    ):
        if key in recorded and recorded[key] != measured.conditions.get(key):
            differing.append(f"{key}: run {measured.conditions.get(key)!r}, baseline {recorded[key]!r}")
    return differing


def _display(path: Path) -> str:
    """Repo-relative where that is meaningful, absolute otherwise.

    An operator may keep their baseline anywhere, including outside the
    checkout, and `relative_to` raises rather than falling back.
    """
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def load_judgements(path: Path) -> tuple[Judgement, ...]:
    """An operator's own query set: a JSON list of query/language/filename/phrase."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path} does not contain a non-empty list of judgements")
    out = []
    for entry in raw:
        missing = {"query", "filename", "phrase"} - set(entry)
        if missing:
            raise ValueError(f"{path}: a judgement is missing {', '.join(sorted(missing))}")
        # An empty phrase is a substring of every passage, so the query would
        # score a perfect hit against any ranking and quietly carry a regressed
        # run over the baseline. A half-finished judgement is refused, not scored.
        for field_name in ("query", "filename", "phrase"):
            if not str(entry[field_name] or "").strip():
                raise ValueError(
                    f"{path}: a judgement has an empty {field_name!r}; "
                    "an empty phrase matches every passage"
                )
        out.append(
            Judgement(
                query=str(entry["query"]),
                language=str(entry.get("language", "en")),
                filename=str(entry["filename"]),
                phrase=str(entry["phrase"]),
                # An operator's corpus has near-duplicates too — a draft, the
                # signed version, an amendment — so their judgements need the
                # same escape the built-in set uses. Without this the harness
                # would score their correct results as wrong.
                also=tuple(
                    (str(alternative["filename"]), str(alternative["phrase"]))
                    for alternative in entry.get("also", ())
                ),
            )
        )
    return tuple(out)


# --- reporting -------------------------------------------------------------


def print_report(measured: Measurement) -> None:
    columns = [f"recall@{k}" for k in RECALL_AT] + [f"mrr@{MRR_AT}"]
    print("Conditions: " + ", ".join(f"{k}={v}" for k, v in measured.conditions.items()))
    if measured.conditions.get("embedder") == "deterministic":
        print(
            "  These figures measure the retrieval mechanism, not retrieval quality:\n"
            "  the deterministic embedder's vectors carry no meaning."
        )
    print()
    header = f"{'':<12}" + "".join(f"{c:>10}" for c in columns)
    print(header)
    print("─" * len(header))
    for leg in ("keyword", "vector", "fused"):
        figures = measured.metrics.get(leg, {})
        print(f"{leg:<12}" + "".join(f"{figures.get(c, 0.0):>10.3f}" for c in columns))
    if measured.by_language:
        print()
        print(f"{'fused by language':<12}")
        for language, figures in measured.by_language.items():
            print(f"{language:<12}" + "".join(f"{figures.get(c, 0.0):>10.3f}" for c in columns))
    missed = [q for q in measured.per_query if q["rank"] is None]
    if missed:
        print(f"\nNot retrieved at all ({len(missed)}):")
        for entry in missed:
            print(f"  [{entry['language']}] {entry['query']} → {entry['expects']}")


# --- entry point -----------------------------------------------------------


def build_evaluation_context(
    workspace: Path,
    embedder: str,
    reranker: str,
    corpus: Path | None,
    window_max_chars: int | None = None,
    chunk_max_chars: int | None = None,
    recognition: bool = True,
):
    """A real instance, wired the way the composition root wires one.

    When the built-in corpus is used the quality gate's rungs are stand-ins, and
    they must never run: every document here is text, so recognition is not part
    of what is being measured, and building the engine would download a model to
    read nothing.

    An operator's own corpus may contain scans, so it gets the real gate — and
    that gate is built before the first document is read, so a text-only corpus
    on a machine with no model weights would otherwise fail for a reason that has
    nothing to do with retrieval. `--no-recognition` is the way to say the corpus
    needs none.
    """
    from jackryan.app import build_context
    from jackryan.config import Config, Contract, Profile
    from jackryan.ingestion.quality_gate import QualityGate

    profile_kwargs: dict[str, Any] = {"name": "evaluate", "embedder": embedder}
    if reranker:
        profile_kwargs["reranker_model"] = reranker
    if window_max_chars is not None:
        profile_kwargs["window_max_chars"] = window_max_chars
    contract = (
        Contract(chunk_max_chars=chunk_max_chars) if chunk_max_chars else Contract()
    )
    config = Config(
        contract=contract,
        profile=Profile(**profile_kwargs),
        data_dir=workspace / "data",
    )

    gate = None
    if corpus is None or not recognition:

        class RungWasReached(BaseException):
            """Not an `Exception`: the ingest service would fold that into a
            per-file failure and the run would look merely disappointing."""

        def unreached(path):
            raise RungWasReached(
                f"a rung reader ran for {path}: this corpus was declared text only"
            )

        gate = QualityGate(
            ocr_engine=config.profile.ocr_engine,
            ocr_language=config.profile.ocr_language,
            min_chars_per_page=config.profile.min_chars_per_page,
            readers={"text-layer": unreached, "ocr": unreached},
        )
    return build_context(config, gate=gate)


def main() -> int:
    parser = argparse.ArgumentParser(description=SUMMARY)
    parser.add_argument(
        "--embedder",
        choices=("model", "deterministic"),
        default="model",
        help="which embedder to measure under; 'deterministic' is the offline control",
    )
    parser.add_argument(
        "--reranker",
        default="",
        help="a reranker model to measure with, or empty for none",
    )
    parser.add_argument("--limit", type=int, default=10, help="results per query")
    parser.add_argument(
        "--window-max-chars",
        type=int,
        help="widen results to this many characters; 1 switches widening off",
    )
    parser.add_argument(
        "--chunk-max-chars",
        type=int,
        help=(
            "chunk the corpus at this width instead of the contract's. A corpus "
            "value, so it builds a different corpus — the workspace is temporary, "
            "and this is how a passage size can be measured rather than assumed"
        ),
    )
    parser.add_argument("--corpus", type=Path, help="measure your own corpus instead")
    parser.add_argument(
        "--no-recognition",
        action="store_true",
        help=(
            "declare your corpus text-only, so no recognition engine is built. "
            "The engine is built before the first document is read, so without "
            "this a text-only corpus still needs model weights on disk"
        ),
    )
    parser.add_argument("--queries", type=Path, help="your own judgements, as JSON")
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument(
        "--record",
        action="store_true",
        help="write this run's figures as the new baseline; never automatic",
    )
    parser.add_argument("--json", type=Path, help="also write the measurement here")
    parser.add_argument("--keep", action="store_true", help="leave the temporary directory")
    args = parser.parse_args()

    if args.limit < max(RECALL_AT):
        parser.error(f"--limit must be at least {max(RECALL_AT)} to measure recall at it")
    if bool(args.corpus) != bool(args.queries):
        parser.error("--corpus and --queries go together: your own corpus needs its own judgements")

    judgements = load_judgements(args.queries) if args.queries else JUDGEMENTS

    workspace = Path(tempfile.mkdtemp(prefix="jackryan-evaluate-"))
    print(f"Workspace: {workspace}\n")
    try:
        corpus = args.corpus
        if corpus is None:
            corpus = workspace / "corpus"
            write_corpus(corpus, DOCUMENTS)

        context = build_evaluation_context(
            workspace,
            args.embedder,
            args.reranker,
            args.corpus,
            args.window_max_chars,
            args.chunk_max_chars,
            recognition=not args.no_recognition,
        )
        try:
            casefile = context.casefiles.create("Retrieval Evaluation")
            report = context.ingestion.ingest(casefile.short_id, corpus)
            if report.failed:
                detail = "; ".join(o.detail for o in report.outcomes if o.status == "failed")
                print(f"Ingest failed: {detail}")
                return 1

            conditions = {
                "embedder": args.embedder,
                "reranker": args.reranker or "none",
                "query_set": "operator" if args.queries else "built-in",
                "queries": len(judgements),
                "documents": report.ingested,
                "chunk_max_chars": context.config.contract.chunk_max_chars,
                "window_max_chars": context.config.profile.window_max_chars,
                "limit": args.limit,
            }
            measured = measure(
                context, casefile.short_id, judgements, limit=args.limit, conditions=conditions
            )
        finally:
            context.close()
    finally:
        if args.keep:
            print(f"Left in place: {workspace}")
        else:
            shutil.rmtree(workspace, ignore_errors=True)

    print_report(measured)

    if args.json:
        args.json.write_text(json.dumps(measured.as_json(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.record:
        payload = measured.as_json()
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"\nBaseline written to {_display(args.baseline)}.")
        print("Recorded deliberately. Say in the commit why the figures moved.")
        return 0

    if not args.baseline.exists():
        print(
            f"\nNo baseline at {args.baseline}. Nothing to compare against; "
            "record one with --record once you are satisfied these figures are right."
        )
        return 0

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    if not baseline.get("metrics"):
        # An empty or absent metrics block would compare against nothing and
        # report success on a run that scored zero everywhere. This is the one
        # thing here that can see retrieval regress; it must not pass by default.
        print(
            f"\nThe baseline at {_display(args.baseline)} records no metrics, so there "
            "is nothing to compare against. Re-record it with --record, or restore it."
        )
        return 1
    differing = conditions_match(measured, baseline)
    if differing:
        print("\nNot compared against the baseline — it was recorded under other conditions:")
        for line in differing:
            print(f"  {line}")
        print("A figure is only comparable against one produced the same way.")
        return 0

    fallen = compare(measured, baseline, TOLERANCE)
    print("─" * 60)
    if fallen:
        print(f"{len(fallen)} metric(s) below the baseline:")
        for line in fallen:
            print(f"  ✗ {line}")
        print(
            "\nRetrieval degrades silently: every search still returns results, and they "
            "are still plausible. This is the only place that failure has a symptom."
        )
        return 1
    print("At or above the baseline on every metric.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
