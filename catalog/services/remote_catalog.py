from tempfile import NamedTemporaryFile

from catalog.models import Shop
from catalog.services.catalog_import import import_catalog
from catalog.services.remote_yaml import download_catalog_yaml


def import_remote_catalog(
    shop: Shop,
    url: str,
) -> dict[str, int]:
    """
    Импортирует каталог поставщика из удалённого YAML-файла.

    Скачивает прайс-лист по URL, сохраняет его
    во временный файл и передаёт существующему
    сервису импорта каталога.

    Временный файл удаляется автоматически
    после завершения операции.

    Args:
        shop (Shop): Магазин, для которого выполняется импорт.
        url (str): HTTP или HTTPS адрес YAML-файла.

    Returns:
        dict[str, int]: Статистика импорта:
            categories — обработанные категории;
            products — обработанные товары;
            parameters — обработанные характеристики;
            deactivated — товары с обнулёнными остатками.

    Raises:
        CatalogDownloadError: Если файл не удалось скачать.
        CatalogImportError: Если содержимое YAML некорректно
            или не соответствует выбранному магазину.
    """
    # Скачиваем YAML-файл.
    content = download_catalog_yaml(url)

    # Создаём временный файл для существующего импортера.
    with NamedTemporaryFile(
        mode="wb",
        suffix=".yaml",
    ) as temporary_file:
        temporary_file.write(content)
        temporary_file.flush()

        # Используем готовый сервис импорта.
        return import_catalog(
            shop=shop,
            file_path=temporary_file.name,
        )
