.PHONY: fmt lint tests coverage

# Запуск форматтеров
fmt:
	@uv run ruff format -q .
	@uv run ruff check -q --fix .
	@echo "✅  Код отформатирован"

# Запуск линтеров (только проверка кода)
lint:
	@uv run ruff format -q --check . || (echo "🔥  Код неотформатирован: make fmt" && exit 1)
	@uv run ruff check -q .
	@uv run ty check -q .
	@echo "✅  Проверки прошли успешно"

# Все проверки
check: fmt lint tests

# Установка зависимостей
deps:
	uv sync --dev

# Запуск тестов (вывод скрыт для агентов)
tests:
	@uv run pytest -q --tb=short --no-header --no-summary
	@echo "✅  Тесты прошли успешно"

# Запуск тестов с полным выводом
ff:
	@uv run pytest -x -v
	@echo "✅  Тесты прошли успешно"

# Запуск тестов с coverage
coverage:
	@uv run pytest --cov --cov-report=term-missing

# Обработка папки импорта
import:
	@PYTHONPATH=src uv run src/scripts/crawler.py
	@PYTHONPATH=src uv run src/scripts/tidy_up_index.py
