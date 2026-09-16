FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYOPENGL_PLATFORM=egl

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends git libegl1 libgl1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-dev.txt requirements-vision.txt ./
RUN python -m pip install --root-user-action=ignore --disable-pip-version-check --no-cache-dir -r requirements-vision.txt

COPY . .

CMD ["sh", "-c", "python scripts/validate-skills.py skills && coverage run --branch -m unittest discover -s development/tests -t . && coverage report --fail-under=55 && ruff check programs scripts development/tests && ruff format --check programs scripts development/tests && mypy && python scripts/validate-schemas.py --manifest visual-reference-evidence=development/config/character-asset-evidence-20260914.json --manifest visual-reference-evidence=development/config/kainin-asset-variants-20260914.json"]
