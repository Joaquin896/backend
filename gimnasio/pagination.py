from rest_framework.pagination import PageNumberPagination


class PaginacionEstandar(PageNumberPagination):
    """Paginación por defecto de la API; el cliente puede pedir hasta 100 por página."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
