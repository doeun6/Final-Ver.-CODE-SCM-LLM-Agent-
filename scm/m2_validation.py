"""Bounded lexical checks for qualitative reasons for the committed M2 order.

Recognizable quantities, statistical values, future actions and ordering advice
are rejected. Categorical current absence ("no backlog", "backlog is zero/0")
is allowed: the spelling of the same absence must not determine acceptance.
The zero exemption is deliberately limited to named current states/orders,
not statistics, forecasts, future plans or arbitrary occurrences of zero.

These checks are not a semantic classifier. They cannot establish factual
accuracy, state ownership, causal support, commitment, or every paraphrase.
Passing this gate is not evidence that a message is truthful or correctly
attributed; those questions need a separate input-versus-message audit.
"""

import re


_NUMBER_WORD = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)"
)
_NUMBER = rf"{_NUMBER_WORD}(?:[\s-]+(?:and\s+)?{_NUMBER_WORD})*"
_QUANTITY_NOUN = (
    r"(?:units?|items?|pieces?|orders?|requests?|periods?|days?|weeks?|percent|"
    r"inventory|stock|backlog|demand|quantity|quantities)"
)
_NUMBER_QUANTITY = re.compile(
    rf"\b{_NUMBER}\s+(?:additional\s+|more\s+|fewer\s+)?{_QUANTITY_NOUN}\b|"
    rf"\b(?:inventory|stock|backlog|demand|quantity|order(?:\s+quantity)?|pipeline|"
    r"mean|average|median|minimum|maximum|variance|standard\s+deviation|ratio|rate)"
    rf"\s*(?:(?:is|was|of|at|equals?|totals?|remains?|for)\s+|[=:]\s*)+{_NUMBER}\b|"
    rf"\b(?:order|ordered|ordering|purchase|purchased|replenish|replenished)"
    rf"\s+(?:(?:another|additional|exactly|only|about|approximately)\s+)?{_NUMBER}\b|"
    r"\b(?:half|quarter|twice|double|triple)\s+(?:(?:of|the|current|my|our)\s+)*"
    r"(?:inventory|stock|backlog|demand|order|quantity)\b",
    re.IGNORECASE,
)
_KOREAN_QUANTITY = re.compile(
    r"(?:[영일이삼사오육칠팔구십백천]+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)"
    r"\s*(?:개|단위|상자|박스|퍼센트)(?=$|[\s.,;!?]|[를가만로은는입이을])"
)

_HORIZON = r"(?:next\s+(?:period|week|day|cycle)|future\s+periods?|tomorrow|later\s+periods?)"
# Exempt only a local assertion of absence, not "mean backlog is zero" or
# "next period's order is zero". A causal explanation starts a new clause, so
# "my current order is zero because expected demand is low" remains allowed.
_CLAUSE_SEPARATOR = re.compile(
    r"([,;!?\n]|(?<!\d)\.(?!\d)|\b(?:because|but|while|whereas)\b)", re.IGNORECASE
)
_NONCURRENT_OR_STATISTICAL_ZERO = re.compile(
    rf"\b(?:{_HORIZON}|future|planned|plan|planning|scheduled|expected|forecast(?:ed)?|"
    r"predicted|prediction|estimate(?:d)?|projected|mean|average|median|minimum|maximum|"
    r"min|max|standard\s+deviation|sd|variance|volatility|ratio|rate|percent|probability)\b|"
    r"다음\s*(?:기|기간|주)|내일|향후|앞으로|예정|계획|예상|예측|추정|"
    r"통계|평균|중앙값|최대|최소|표준편차|분산|확률|비율",
    re.IGNORECASE,
)
_ZERO = r"(?:zero|0(?:\.0+)?)"
_ABSENCE_NOUN = (
    r"(?:inventory|stock|backlogs?|pipeline|outstanding\s+orders?|unfilled\s+orders?|"
    r"unmet\s+demand|demand|(?:(?:current|committed|final)\s+)?orders?(?:\s+quantity)?)"
)
_CURRENT_ZERO = re.compile(
    rf"\b{_ABSENCE_NOUN}\s*(?:(?:currently|now)\s+)?"
    rf"(?:(?:is|are|equals?|remains?|at)\s+|[=:]\s*)"
    r"(?:(?:currently|now)\s+)?(?:at\s+)?"
    rf"{_ZERO}(?!\w|\.\d)(?:\s+units?\b)?|"
    rf"\b{_ZERO}\s+(?:current\s+)?{_ABSENCE_NOUN}\b|"
    rf"\b(?:ordered|purchased|submitted|placed)\s+{_ZERO}(?!\w|\.\d)\s+(?:units?|orders?)\b",
    re.IGNORECASE,
)
# Keep the immediately preceding named state attached to its zero predicate
# before splitting on commas. This handles the R3 pilot's "inventory, which
# is currently zero" without exempting unnamed zeros or broad relative clauses.
_RELATIVE_CURRENT_ZERO = re.compile(
    rf"\b({_ABSENCE_NOUN})\s*,?\s*(?:which|that)\s+(is|are)\s+"
    rf"(?=(?:(?:currently|now)\s+)?(?:at\s+)?{_ZERO}(?!\w|\.\d))",
    re.IGNORECASE,
)
_KOREAN_CURRENT_ZERO = re.compile(
    r"(?:재고|백로그|미입고\s*주문(?:량)?|미충족\s*수요|수요|"
    r"(?:(?:현재|당기|확정|최종)\s*)?(?:주문량|발주량))"
    r"(?:은|는|이|가)?\s*(?:=\s*)?(?:0(?:\.0+)?|영|제로)"
    r"(?:\s*(?:개|단위))?(?:입니다|이다|이며|이고|이므로|여서|(?=$|[\s,.]))"
)


def _quantity_text_with_current_absence_masked(message):
    quantity_text = _RELATIVE_CURRENT_ZERO.sub(r"\1 \2 ", message)
    parts = _CLAUSE_SEPARATOR.split(quantity_text)
    for index in range(0, len(parts), 2):
        clause = parts[index]
        if not _NONCURRENT_OR_STATISTICAL_ZERO.search(clause):
            clause = _CURRENT_ZERO.sub("categorical absence", clause)
            clause = _KOREAN_CURRENT_ZERO.sub("현재 부재", clause)
        parts[index] = clause
    text = "".join(parts)
    # Category membership, unlike "one unit", is not a quantity.
    return re.sub(r"\bone\s+of\b", "a member of", text, flags=re.IGNORECASE)


_ACTION = (
    r"(?:place|submit|order|reorder|replenish|purchase|buy|ship|dispatch|send|"
    r"increase|decrease|reduce|raise|stop|resume|maintain|continue|adjust|hold)"
)
_GERUND_ACTION = (
    r"(?:placing|submitting|ordering|reordering|replenishing|purchasing|buying|"
    r"shipping|dispatching|sending|increasing|decreasing|reducing|raising|stopping|"
    r"resuming|maintaining|continuing|adjusting|holding)"
)
_ORDER_CONTINUATION = r"proceed\s+with\s+(?:(?:my|our|the|a|an|current|committed)\s+)*orders?"
_ACTION_EXPRESSION = rf"(?:{_ACTION}\b|{_ORDER_CONTINUATION}\b)"
_SUBJECT = r"(?:I|we|you|they|(?:the\s+)?(?:retailer|wholesaler|distributor|factory|supplier|customer))"
_FUTURE_ACTION = re.compile(
    rf"\b{_SUBJECT}\s+(?:will|shall|would|should|must)\s+(?:not\s+)?{_ACTION_EXPRESSION}|"
    rf"\b{_SUBJECT}\s+(?:am|are|is)\s+going\s+to\s+{_ACTION_EXPRESSION}|"
    rf"\b{_SUBJECT}\s+(?:plan(?:s|ning)?|intend(?:s|ing)?|aim(?:s|ing)?)\s+"
    rf"(?:to\s+{_ACTION_EXPRESSION}|on\s+{_GERUND_ACTION}\b)|"
    rf"\b(?:please|you\s+need\s+to|you\s+ought\s+to)\s+{_ACTION_EXPRESSION}|"
    rf"\bconsider\s+{_GERUND_ACTION}\b",
    re.IGNORECASE,
)
_PRESENT_ACTION = (
    r"(?:place|places|submit|submits|order|orders|reorder|reorders|replenish|replenishes|purchase|purchases|"
    r"buy|buys|ship|ships|dispatch|dispatches|send|sends|increase|increases|decrease|decreases|"
    r"reduce|reduces|raise|raises|stop|stops|resume|resumes|maintain|maintains|continue|continues|"
    r"adjust|adjusts|hold|holds)"
)
_PASSIVE_ORDER_ACTION = (
    r"(?:placed|submitted|increased|decreased|reduced|raised|stopped|resumed|maintained|"
    r"continued|adjusted|shipped|dispatched)"
)
# Future demand can explain the committed current order; it is not itself a
# future ordering action. Keep purpose/evidence clauses out of this pattern.
_BEFORE_HORIZON = (
    r"(?:\s+(?!(?:to|because|since|as|for|cover|covers|address|addresses|"
    r"meet|meets|support|supports|expected)\b)[a-z'-]+){0,6}"
)
_TEMPORAL_ACTION = re.compile(
    rf"\b{_HORIZON}\b\s*,?\s*{_SUBJECT}\s+{_PRESENT_ACTION}\b|"
    rf"\b{_HORIZON}\b\s*,?\s*(?:our\s+|the\s+)?orders?\s+(?:is|are)\s+{_PASSIVE_ORDER_ACTION}\b|"
    rf"\b{_SUBJECT}\s+{_PRESENT_ACTION}\b{_BEFORE_HORIZON}\s+{_HORIZON}\b|"
    rf"\borders?\s+(?:is|are)\s+{_PASSIVE_ORDER_ACTION}\b{_BEFORE_HORIZON}\s+{_HORIZON}\b",
    re.IGNORECASE,
)
_PASSIVE_FUTURE_ACTION = re.compile(
    r"\b(?:orders?|replenishment|shipments?)\s+(?:will|shall|should|must)\s+(?:not\s+)?be\s+"
    rf"{_PASSIVE_ORDER_ACTION}\b|"
    r"\borders?\s+(?:is|are)\s+(?:planned|scheduled)\s+(?:for|to)\b",
    re.IGNORECASE,
)
_NOW = r"(?:at\s+this\s+time|now|this\s+period|in\s+the\s+current\s+period)"
_CURRENT_MODAL_ACTION = re.compile(
    rf"\b(?:{_SUBJECT}\s+(?:will|shall)\s+(?:not\s+)?{_ACTION_EXPRESSION}|"
    rf"orders?\s+(?:will|shall)\s+(?:not\s+)?be\s+{_PASSIVE_ORDER_ACTION}\b)"
    r"(?:\s+(?!(?:but|and|because|since|tomorrow|next|future|later)\b)[a-z'-]+){0,18}?"
    rf"\s+{_NOW}\b",
    re.IGNORECASE,
)
_KOREAN_CURRENT_MODAL_ACTION = re.compile(
    r"(?:이번(?:\s*기)?(?:에는|에|은)?|현재(?:는)?|지금)\s*"
    r"(?:(?:확정한|확정된|추가)\s*)?(?:주문|발주)(?:을|를)?\s*"
    r"(?:(?:진행|실행)\s*)?(?:하겠습니다|하지\s*않겠습니다|안\s*하겠습니다)"
)
_KOREAN_FUTURE_ACTION = re.compile(
    r"(?:주문|발주|보충|출고|배송|증가|감소|중단|재개)[^.。!?\n]{0,35}"
    r"(?:(?:할|될)\s*(?:계획|예정|것)|하겠|하려고|할게|늘리겠|줄이겠)|"
    r"(?:다음\s*(?:기간|기|주)|향후|내일)(?:에는|에|은|부터)?\s*"
    r"(?:(?:소매점|도매점|유통업체|공장|저|우리)(?:은|는|이|가)?\s*)?"
    r"(?:추가\s*)?(?:주문|발주|보충|출고|배송)|"
    r"(?:주문|발주|보충|출고)[^.。!?\n]{0,20}"
    r"(?:하세요|하십시오|해야\s*합니다|늘리세요|줄이세요|늘려\s*주세요|줄여\s*주세요)"
)


def _future_action_text(message):
    normalized = message.replace("’", "'")
    normalized = re.sub(r"\b(I|we|you|they|retailer|wholesaler|distributor|factory|supplier)'ll\b",
                        r"\1 will", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bwon't\b", "will not", normalized, flags=re.IGNORECASE)

    def mask_current(match):
        # Do not erase a mixed-time plan such as "I will order now and tomorrow".
        # Other clauses are checked independently after this local exemption.
        start = max(normalized.rfind(mark, 0, match.start()) for mark in ",;.!?\n") + 1
        if re.search(rf"\b{_HORIZON}\b|다음\s*(?:기|주)|내일|향후", normalized[start:match.start()], re.IGNORECASE):
            return match.group()
        tail = normalized[match.end():]
        if re.match(rf"\s*(?:and|or|및|그리고)\s*(?:{_HORIZON}|다음\s*기|내일)", tail, re.IGNORECASE):
            return match.group()
        return "the current committed action"

    remaining = _CURRENT_MODAL_ACTION.sub(mask_current, normalized)
    # The Korean grammar is intentionally limited to explicit present markers
    # and current order verbs; other future clauses remain visible to the gate.
    remaining = _KOREAN_CURRENT_MODAL_ACTION.sub("현재 확정한 주문", remaining)
    return remaining


def validate_m2_message(message):
    """Reject recognizable content violations, without claiming semantic validity."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("M2 message must be nonblank text")
    quantity_text = _quantity_text_with_current_absence_masked(message)
    if (re.search(r"\d|\bzero\b", quantity_text, flags=re.IGNORECASE)
            or _NUMBER_QUANTITY.search(quantity_text) or _KOREAN_QUANTITY.search(quantity_text)):
        raise ValueError("M2 permits qualitative reasons only, without numeric quantities except categorical current absence")

    remaining = _future_action_text(message)
    if (_FUTURE_ACTION.search(remaining) or _TEMPORAL_ACTION.search(remaining)
            or _PASSIVE_FUTURE_ACTION.search(remaining) or _KOREAN_FUTURE_ACTION.search(remaining)):
        raise ValueError("M2 must not include future action plans or ordering advice")

