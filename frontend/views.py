from django.shortcuts import render


def dashboard(request):
    return render(request, 'frontend/dashboard.html')


def board(request):
    return render(request, 'frontend/board.html')


def score_idea(request):
    return render(request, 'frontend/score.html')


def idea_detail(request, idea_id):
    return render(request, 'frontend/idea_detail.html', {'idea_id': idea_id})


def research(request):
    return render(request, 'frontend/research.html')


def ba_explorer(request):
    return render(request, 'frontend/ba_explorer.html')


def scoring_guide(request):
    return render(request, 'frontend/scoring_guide.html')


def documents(request):
    return render(request, 'frontend/documents.html')


def doc_amazon_research(request):
    return render(request, 'frontend/doc_amazon_research.html')


def doc_ba(request):
    return render(request, 'frontend/doc_ba.html')


def doc_api(request):
    return render(request, 'frontend/doc_api.html')


def keyword_suggestions(request):
    examples = ['shirts', 'yoga mat', 'dog leash', 'bamboo mug', 'car sun shade', 'kitchen knife', 'baby monitor']
    return render(request, 'frontend/keyword_suggestions.html', {'examples': examples})
