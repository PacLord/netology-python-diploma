from pathlib import Path
from typing import Any

import yaml


class CatalogImportError(ValueError):
    """
    Ошибка чтения или валидации импортируемого каталога.

    Используется для передачи понятных сообщений
    об ошибках входных данных.
    """


def load_catalog_yaml(file_path: str | Path) -> dict[str, Any]:
    """
    Загружает YAML-файл с каталогом товаров поставщика.

    Проверяет возможность чтения файла и наличие основных
    разделов каталога. Детальная проверка товаров и категорий
    выполняется на отдельном этапе.

    Args:
        file_path (str | Path): Путь к YAML-файлу поставщика.

    Returns:
        dict[str, Any]: Данные каталога в виде словаря Python.

    Raises:
        CatalogImportError: Если файл невозможно прочитать,
            YAML имеет некорректный формат или отсутствуют
            обязательные разделы каталога.
    """
    path = Path(file_path)

    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)

    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise CatalogImportError(
            f"Не удалось прочитать YAML-файл '{path}': {error}"
        ) from error

    if not isinstance(data, dict):
        raise CatalogImportError("Корневой элемент YAML должен быть словарём.")

    if not isinstance(data.get("shop"), str) or not data["shop"].strip():
        raise CatalogImportError("Необходимо указать название магазина в поле 'shop'.")

    for field in ("categories", "goods"):
        if not isinstance(data.get(field), list):
            raise CatalogImportError(f"Поле '{field}' должно содержать список.")

    return data
