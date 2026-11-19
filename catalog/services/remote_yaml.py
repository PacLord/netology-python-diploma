import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 МБ
REQUEST_TIMEOUT = 10  # секунд


class CatalogDownloadError(ValueError):
    """
    Ошибка скачивания прайс-листа поставщика.

    Возникает при недопустимом URL, сетевой ошибке,
    превышении размера файла или ошибке HTTP.
    """


def download_catalog_yaml(url: str) -> bytes:
    """
    Скачивает YAML-файл поставщика по HTTP или HTTPS.

    Проверяет IP-адреса сервера и запрещает обращения
    к локальным и внутренним сетям.

    Ограничивает размер файла и время ожидания
    сетевых операций. Не следует перенаправлениям.

    Args:
        url (str): URL прайс-листа поставщика.

    Returns:
        bytes: Содержимое скачанного файла.

    Raises:
        CatalogDownloadError: Если адрес недопустим,
            сервер недоступен или файл слишком большой.
    """
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise CatalogDownloadError("URL содержит недопустимые символы.")

    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise CatalogDownloadError("Некорректный URL.") from error

    scheme = parsed.scheme.lower()

    if scheme not in ("http", "https") or not host:
        raise CatalogDownloadError("Разрешены только HTTP и HTTPS адреса.")

    if parsed.username is not None or parsed.password is not None:
        raise CatalogDownloadError("URL не должен содержать учётные данные.")

    port = port or (443 if scheme == "https" else 80)

    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise CatalogDownloadError("Некорректное имя сервера.") from error

    # Разрешаем DNS-имя и проверяем все IP-адреса.
    try:
        addresses = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as error:
        raise CatalogDownloadError("Не удалось определить IP-адрес сервера.") from error

    if not addresses or any(
        not ipaddress.ip_address(item[4][0]).is_global for item in addresses
    ):
        raise CatalogDownloadError(
            "Загрузка из локальных или внутренних сетей запрещена."
        )

    # Подключаемся к уже проверенному IP,
    # чтобы не выполнять повторное DNS-разрешение.
    server_ip = str(addresses[0][4][0])

    path = parsed.path or "/"

    if parsed.query:
        path = f"{path}?{parsed.query}"

    connection = http.client.HTTPConnection(
        host,
        port,
        timeout=REQUEST_TIMEOUT,
    )

    raw_socket = None
    transport = None

    try:
        raw_socket = socket.create_connection(
            (server_ip, port),
            timeout=REQUEST_TIMEOUT,
        )

        if scheme == "https":
            context = ssl.create_default_context()

            transport = context.wrap_socket(
                raw_socket,
                server_hostname=host,
            )
        else:
            transport = raw_socket

        connection.sock = transport

        connection.request(
            "GET",
            path,
            headers={"Accept-Encoding": "identity"},
        )

        response = connection.getresponse()

        if response.status != 200:
            raise CatalogDownloadError(
                f"Сервер вернул HTTP {response.status}. "
                "Перенаправления не поддерживаются."
            )

        content_length = response.getheader("Content-Length")

        if (
            content_length is not None
            and content_length.isdecimal()
            and int(content_length) > MAX_FILE_SIZE
        ):
            raise CatalogDownloadError("Размер прайс-листа превышает 2 МБ.")

        # Читаем не больше установленного лимита + 1 байт.
        content = response.read(MAX_FILE_SIZE + 1)

        if len(content) > MAX_FILE_SIZE:
            raise CatalogDownloadError("Размер прайс-листа превышает 2 МБ.")

        return content

    except (OSError, http.client.HTTPException) as error:
        raise CatalogDownloadError("Не удалось скачать прайс-лист.") from error

    finally:
        connection.close()

        if transport is not None:
            transport.close()

        if raw_socket is not None:
            raw_socket.close()
