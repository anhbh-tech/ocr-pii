# Đường chạy chuẩn của ocr-lab.
#
# Vì sao có tệp này: các lệnh dưới đây đều đã từng bị chạy SAI một lần —
# sai model (nano 171 MB thay vì teacher 904 MB), sai thước đo, hoặc gọi API
# mất tiền khi chỉ định đo thử. Ghi lại thành target để lần sau không phải
# nhớ, và để mặc định an toàn là mặc định mà gõ ít chữ nhất.
#
# Quy ước:
#   - target KHÔNG mất tiền chạy thẳng.
#   - target GỌI API TRẢ PHÍ bắt buộc CONFIRM=1.

SHELL := /bin/bash
PY    := uv run python

#: Model mặc định — teacher 904 MB v1.3.1. KHÔNG dùng nano cho việc thật.
MODEL ?= protonx-legal-tc
STORE ?= $(HOME)/.private/ade_out
PORT  ?= 8811

.DEFAULT_GOAL := help
.PHONY: help test check web web-tailnet classify-api vision ade-pro compare anh-co-chu doc-anh correct correct-write correct-nano ade ade-dry \
        tokens clean-web che che-dry test-ocr-lab test-pii-core pii-core-serve

help:  ## Danh sách target
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ── kiểm thử ───────────────────────────────────────────────────────────

test: test-ocr-lab test-pii-core  ## Chạy toàn bộ test (ocr-lab + pii-core/)

test-ocr-lab:  ## Test của ocr-lab
	$(PY) -m pytest tests/ -q

test-pii-core:  ## Test của pii-core/ (project uv riêng, chỉ thư viện chuẩn)
	cd pii-core && uv run --extra dev pytest -q

check: test  ## Test + kiểm kiểu
	$(PY) -m pyright src/ scripts/ 2>/dev/null || true

# ── sửa chính tả (KHÔNG gọi API, chỉ chạy model cục bộ) ────────────────

# `--force` là mặc định có chủ ý: cổng mật độ dấu dựa trên accent_share, mà
# thước đó đếm SỐ LƯỢNG dấu chứ không đếm dấu ĐÚNG/SAI ('điện tứ' và 'điện
# tử' cho cùng một con số). Nó chặn đúng loại lỗi ta cần sửa, nên để nguyên
# thì lệnh này luôn báo "không có việc gì làm" — sai sự thật.
FORCE ?= --force

correct:  ## Đo lớp sửa chính tả trên kho ADE (chỉ đo, không ghi)
	$(PY) scripts/measure_ade_postcorrect.py --model $(MODEL) --store $(STORE) $(FORCE)

correct-write:  ## Như trên nhưng GHI corrected.json vào kho
	$(PY) scripts/measure_ade_postcorrect.py --model $(MODEL) --store $(STORE) $(FORCE) --write

correct-nano:  ## Đối chứng bằng nano 171MB (để so, không dùng cho việc thật)
	$(PY) scripts/measure_ade_postcorrect.py --model nano-protonx-legal-tc --store $(STORE) $(FORCE)

ade-pro:  ## ADE Pro trên hợp đồng+CCCD — TỐN TIỀN (0,9 cr/trang), cần CONFIRM=1
ifneq ($(CONFIRM),1)
	@$(PY) scripts/run_ade_pro.py --store $(STORE)
	@echo ""
	@echo "Chạy thật: make ade-pro CONFIRM=1"
	@exit 1
endif
	$(PY) scripts/run_ade_pro.py --store $(STORE) --yes

doc-anh:  ## Đọc chữ trong ảnh nhúng của trang digital (Vision, miễn phí)
	$(PY) scripts/read_embedded_images.py --max-files 120 --write

anh-co-chu:  ## Dò chữ nằm trong ảnh trên trang đã gắn nhãn digital (Vision, miễn phí)
	$(PY) scripts/detect_text_in_images.py --max-files 120

compare:  ## So 3 engine (Verity / Pro / Vision) — chỉ đọc kho, không tốn tiền
	$(PY) scripts/compare_engines.py --store $(STORE)

# pii-core/ là mã pii-core đi cùng repo. Khoá và roster ở ngoài
# cây: PII_CORE_KEY hoặc PII_CORE_KEY_FILE, PII_CORE_ROSTER (~/.private/pii-core/).
pii-core-serve:  ## Chạy pii-core serve từ pii-core/ (127.0.0.1:8813; cần khoá)
	cd pii-core && uv run python -m pii_core serve

che-dry:  ## Đếm vùng PII sẽ che trên kho (pii-core quyết), không ghi
	$(PY) scripts/che_pii.py --all --dry --store $(STORE)

che:  ## Che PII lên ảnh trang bằng box ADE Pro → ~/.private/che (cục bộ, miễn phí)
	$(PY) scripts/che_pii.py --all --store $(STORE)

vision:  ## Chạy Apple Vision lên kho (cục bộ, miễn phí) để đối chiếu với ADE
	$(PY) scripts/run_vision_on_store.py --store $(STORE)

tokens:  ## Đo tỉ lệ token/từ trên kho — căn cứ chọn trần chia khối
	@$(PY) -c "import sys,json,glob,statistics as st; sys.path.insert(0,'src'); \
	from ocr_lab.postcorrect import PostCorrector, DEFAULT_MAX_INPUT_TOKENS as T; \
	tk=PostCorrector()._load_tokenizer(); \
	L=[l for f in glob.glob('$(STORE)/*/parse.json') for l in json.load(open(f)).get('markdown','').split(chr(10)) if l.strip()]; \
	r=[len(tk(l).input_ids)/max(1,len(l.split())) for l in L]; s=sorted(r); \
	print(f'{len(L)} dòng | token/từ: trung vị {st.median(r):.1f} · p95 {s[int(.95*len(s))]:.1f} · tệ nhất {max(r):.1f}'); \
	print(f'trần hiện tại: {T} token/khối')" 2>&1 | grep -v Loading

# ── web đối chiếu ──────────────────────────────────────────────────────

web:  ## Web đối chiếu, chỉ máy này (127.0.0.1:8811)
	$(PY) scripts/serve_review.py

web-tailnet:  ## Web đối chiếu, xem được từ máy khác trong tailnet
	$(PY) scripts/serve_review.py --tailnet

classify-api:  ## POST /api/classify cho jev ai, chỉ máy này (127.0.0.1:8812)
	$(PY) scripts/serve_classify.py

# ── ADE: GỌI API TRẢ PHÍ ───────────────────────────────────────────────

ade-dry:  ## Xem sẽ gửi những trang nào (không tốn tiền)
	$(PY) scripts/run_ade_pipeline.py --dry-run

ade:  ## Chạy ADE thật — TỐN TIỀN, cần CONFIRM=1
ifneq ($(CONFIRM),1)
	@echo "Lệnh này GỌI API TRẢ PHÍ (0,3 credits ≈ \$$0,003 mỗi trang)."
	@echo "Chạy lại với: make ade CONFIRM=1"
	@exit 1
endif
	$(PY) scripts/run_ade_pipeline.py
