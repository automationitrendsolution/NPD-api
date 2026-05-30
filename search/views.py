from rest_framework.decorators import api_view
from rest_framework.response import Response

from .scraper import fetch_amazon_search
from .parser import parse_amazon_results


@api_view(["GET"])
def amazon_search(request):
    
    keyword = request.GET.get("keyword")

    if not keyword:
        return Response(
            {"error": "keyword required"},
            status=400
        )

    try:
        html = fetch_amazon_search(keyword)

        products = parse_amazon_results(html)

        return Response({
            "keyword": keyword,
            "product_count": len(products),
            "products": products
        })

    except Exception as e:
        return Response(
            {"error": str(e)},
            status=500
        )