"""가벼운 쇼핑 리스트 앱 (Streamlit)."""

import html
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import streamlit as st

DATA_FILE = Path(__file__).parent / "data" / "shopping_list.json"
MAX_NAME_LENGTH = 50
MIN_QUANTITY, MAX_QUANTITY = 1, 999
EMPTY_NAME_WARNING = "아이템 이름을 입력해 주세요."


# ---------- 데이터 처리 ----------

@st.cache_resource
def get_file_lock() -> threading.Lock:
    """모든 세션(탭)이 함께 쓰는 파일 잠금."""
    return threading.Lock()


def is_valid_item(item: object) -> bool:
    """파일에서 읽은 아이템이 데이터 모델(PRD 4장)에 맞는지 확인한다."""
    return (
        isinstance(item, dict)
        and isinstance(item.get("id"), str) and isinstance(item.get("created_at"), str)
        and isinstance(item.get("name"), str) and bool(item["name"].strip())
        and type(item.get("quantity")) is int and isinstance(item.get("checked"), bool)
    )


def load_items() -> list[dict]:
    """DATA_FILE에서 아이템 목록을 불러온다. 파일이 없거나 깨졌으면 빈 목록, 잘못된 아이템은 건너뛴다."""
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # ValueError: JSON 문법 오류, 인코딩 오류
        return []
    return [item for item in data if is_valid_item(item)] if isinstance(data, list) else []


def save_items(items: list[dict]) -> None:
    """임시 파일에 쓴 뒤 교체해서, 저장 중에 끊겨도 기존 파일이 깨지지 않게 한다."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = DATA_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_file, DATA_FILE)


@contextmanager
def edit_items() -> Iterator[list[dict]]:
    """파일에서 최신 목록을 읽어 수정한 뒤 저장한다. 다른 탭의 변경을 덮어쓰지 않도록 매번 다시 읽는다."""
    with get_file_lock():
        items = load_items()
        yield items
        save_items(items)


def find_item(items: list[dict], item_id: str) -> dict | None:
    """id에 해당하는 아이템을 찾는다."""
    return next((i for i in items if i["id"] == item_id), None)


def add_item(name: str, quantity: int = 1) -> None:
    """새 아이템을 목록 끝에 추가한다."""
    with edit_items() as items:
        items.append({
            "id": str(uuid.uuid4()), "name": name, "quantity": quantity, "checked": False,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })


def update_item(item_id: str, name: str, quantity: int) -> None:
    """id에 해당하는 아이템의 이름과 수량을 바꾼다."""
    with edit_items() as items:
        item = find_item(items, item_id)
        if item:
            item.update(name=name, quantity=quantity)


def delete_item(item_id: str) -> None:
    """id에 해당하는 아이템을 삭제한다."""
    with edit_items() as items:
        items[:] = [item for item in items if item["id"] != item_id]


def set_checked(item_id: str) -> None:
    """체크박스 값을 아이템에 반영한다. 뒤집지 않고 값을 그대로 넣어, 다른 탭과 상태가 어긋나지 않게 한다."""
    with edit_items() as items:
        item = find_item(items, item_id)
        if item:
            item["checked"] = st.session_state[f"check_{item_id}"]


def clear_checked() -> None:
    """체크된 아이템을 모두 삭제한다."""
    with edit_items() as items:
        items[:] = [item for item in items if not item["checked"]]


def clear_all() -> None:
    """모든 아이템을 삭제한다."""
    with edit_items() as items:
        items.clear()
    st.session_state["confirm_clear_all"] = False


# ---------- 콜백 ----------

def validate(name: str, quantity: int | None) -> str | None:
    """입력값 검증. 문제가 있으면 경고 문구를 돌려준다."""
    if not name:
        return EMPTY_NAME_WARNING
    if len(name) > MAX_NAME_LENGTH:
        return f"이름은 {MAX_NAME_LENGTH}자 이내로 입력해 주세요. (지금 {len(name)}자)"
    if quantity is None or not MIN_QUANTITY <= quantity <= MAX_QUANTITY:
        return f"수량은 {MIN_QUANTITY}~{MAX_QUANTITY} 사이로 입력해 주세요."
    return None


def handle_add() -> None:
    """입력 폼 제출: 검증 후 추가. 성공했을 때만 입력창을 비워, 실패하면 입력값을 고칠 수 있게 한다."""
    name = st.session_state["new_name"].strip()
    quantity = st.session_state["new_quantity"]
    message = validate(name, quantity)
    if message:
        st.session_state["add_message"] = message
        return
    # 추가 버튼 더블클릭 시 같은 값이 두 번 제출되므로, 직전과 같은 입력이 1초 안에 오면 무시한다.
    submission = (name, quantity)
    last_submission, last_time = st.session_state.get("last_add", (None, 0.0))
    if submission == last_submission and time.monotonic() - last_time < 1.0:
        return
    st.session_state["last_add"] = (submission, time.monotonic())
    add_item(name, int(quantity))
    st.session_state["new_name"] = ""
    st.session_state["new_quantity"] = 1


def start_edit(item_id: str) -> None:
    """편집 모드로 전환하고 입력창에 현재 값을 채운다."""
    item = find_item(st.session_state["items"], item_id)
    if item:
        st.session_state["editing_id"] = item_id
        st.session_state[f"edit_name_{item_id}"] = item["name"]
        st.session_state[f"edit_quantity_{item_id}"] = item["quantity"]


def save_edit(item_id: str) -> None:
    """편집 내용 저장: 검증 실패 시 편집 모드 유지."""
    name = st.session_state[f"edit_name_{item_id}"].strip()
    quantity = st.session_state[f"edit_quantity_{item_id}"]
    message = validate(name, quantity)
    if message:
        st.session_state["edit_message"] = message
        return
    update_item(item_id, name, int(quantity))
    st.session_state["editing_id"] = None


def set_state(key: str, value: object) -> None:
    """편집 취소, 전체 삭제 확인 등 상태값 하나만 바꾸는 콜백."""
    st.session_state[key] = value


# ---------- 화면 ----------

# 모바일(640px 이하)에서 Streamlit이 컬럼을 세로로 쌓는 것을 막고, 완료 아이템 스타일을 정의한다.
CUSTOM_CSS = """
<style>
.st-key-add-area [data-testid="stHorizontalBlock"],
.st-key-item-list [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; gap: 0.5rem; }
.st-key-add-area [data-testid="stColumn"],
.st-key-item-list [data-testid="stColumn"] { min-width: 0 !important; }
.item-name { word-break: break-all; line-height: 1.5; }
.item-name.done { text-decoration: line-through; opacity: 0.45; }
.item-qty { opacity: 0.6; font-size: 0.9em; margin-left: 0.3rem; }
</style>
"""


def show_message(key: str) -> None:
    """콜백이 남긴 경고 문구를 한 번 보여준다."""
    if message := st.session_state.pop(key, None):
        st.warning(message)


def render_summary() -> None:
    """전체/완료 개수와 진행률."""
    items = st.session_state["items"]
    total = len(items)
    done = sum(item["checked"] for item in items)
    percent = round(done / total * 100) if total else 0
    st.caption(f"전체 {total}개 · 완료 {done}개 · {percent}%")
    st.progress(done / total if total else 0.0)


def render_input_form() -> None:
    """아이템 입력 폼: 이름 / 수량 / 추가 버튼을 한 줄에 배치."""
    with st.container(key="add-area"), st.form("add_form", border=False):
        col_name, col_quantity, col_add = st.columns([0.55, 0.25, 0.2], vertical_alignment="bottom")
        col_name.text_input("아이템 이름", placeholder="살 물건을 입력하세요", key="new_name")
        # min/max를 위젯에 걸면 범위 밖 값에서 커서가 수량 칸에 갇히므로, 범위는 validate()에서 확인한다.
        col_quantity.number_input("수량", value=1, step=1, key="new_quantity")
        col_add.form_submit_button("추가", type="primary", on_click=handle_add, width="stretch")
    show_message("add_message")


def render_view_row(item: dict) -> None:
    """일반 행: 체크박스 + 이름 x수량 + 수정/삭제 버튼."""
    item_id = item["id"]
    col_check, col_name, col_edit, col_delete = st.columns(
        [0.08, 0.72, 0.1, 0.1], vertical_alignment="center"
    )
    # 다른 탭에서 바뀐 체크 상태가 보이도록 매번 파일 값으로 맞춘다.
    st.session_state[f"check_{item_id}"] = item["checked"]
    col_check.checkbox(
        item["name"], key=f"check_{item_id}", on_change=set_checked, args=(item_id,),
        label_visibility="collapsed",
    )
    done_class = " done" if item["checked"] else ""
    with col_name:
        st.html(
            f'<div class="item-name{done_class}">{html.escape(item["name"])}'
            f'<span class="item-qty">x{item["quantity"]}</span></div>'
        )
    # 다른 아이템을 편집 중이면 저장/취소 전까지 ✏️를 막아, 편집 내용이 말없이 버려지지 않게 한다.
    col_edit.button(
        "✏️", key=f"edit_{item_id}", help="수정", type="tertiary", on_click=start_edit,
        args=(item_id,), disabled=st.session_state["editing_id"] is not None,
    )
    col_delete.button(
        "🗑️", key=f"delete_{item_id}", help="삭제", type="tertiary", on_click=delete_item,
        args=(item_id,),
    )


def render_edit_row(item: dict) -> None:
    """편집 행: 이름/수량 입력 + 저장/취소 버튼. 폼이라서 Enter로도 저장된다."""
    item_id = item["id"]
    with st.form(f"edit_form_{item_id}", border=False):
        col_name, col_quantity, col_save, col_cancel = st.columns(
            [0.45, 0.25, 0.15, 0.15], vertical_alignment="center"
        )
        col_name.text_input("이름", key=f"edit_name_{item_id}", label_visibility="collapsed")
        col_quantity.number_input(
            "수량", step=1, key=f"edit_quantity_{item_id}", label_visibility="collapsed"
        )
        col_save.form_submit_button(
            "✔", key=f"save_{item_id}", help="저장", type="primary",
            on_click=save_edit, args=(item_id,),
        )
        col_cancel.form_submit_button(
            "✕", key=f"cancel_{item_id}", help="취소", on_click=set_state, args=("editing_id", None)
        )
    show_message("edit_message")


def render_item_list() -> None:
    """미완료 → 완료 순, 같은 그룹 안에서는 추가한 순서로 표시."""
    items = st.session_state["items"]
    if not items:
        st.info("아직 아이템이 없어요. 위에서 추가해 보세요!")
        return
    # 행마다 key를 주면 체크로 순서가 바뀌는 중에 연타할 때 이전 행이 남아서, 바깥에만 고정 key를 준다.
    with st.container(key="item-list"):
        for item in sorted(items, key=lambda i: (i["checked"], i["created_at"])):
            with st.container(border=True):
                editing = item["id"] == st.session_state["editing_id"]
                (render_edit_row if editing else render_view_row)(item)


def render_bulk_actions() -> None:
    """완료 항목 삭제 / 전체 삭제(확인 단계 포함)."""
    items = st.session_state["items"]
    if not items:
        st.session_state["confirm_clear_all"] = False
        return
    if st.session_state["confirm_clear_all"]:
        st.warning("정말 모든 아이템을 삭제할까요?")
        col_yes, col_no = st.columns(2)
        col_yes.button("모두 삭제", type="primary", on_click=clear_all, width="stretch")
        col_no.button(
            "취소", key="cancel_clear_all", on_click=set_state,
            args=("confirm_clear_all", False), width="stretch",
        )
        return
    col_checked, col_all = st.columns(2)
    col_checked.button(
        "완료 항목 삭제", on_click=clear_checked, width="stretch",
        disabled=not any(item["checked"] for item in items),
    )
    col_all.button(
        "전체 삭제", on_click=set_state, args=("confirm_clear_all", True), width="stretch"
    )


def main() -> None:
    st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")
    st.session_state.setdefault("editing_id", None)
    st.session_state.setdefault("confirm_clear_all", False)
    # 다른 탭에서 바뀐 내용도 보이도록 화면을 그릴 때마다 파일에서 다시 읽는다.
    with get_file_lock():
        st.session_state["items"] = load_items()
    editing_id = st.session_state["editing_id"]
    if editing_id and not find_item(st.session_state["items"], editing_id):
        st.session_state["editing_id"] = None  # 다른 탭에서 삭제된 아이템

    st.html(CUSTOM_CSS)
    st.title("🛒 쇼핑 리스트")
    render_summary()
    render_input_form()
    st.divider()
    render_item_list()
    render_bulk_actions()


main()
