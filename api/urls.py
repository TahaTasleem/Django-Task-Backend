from django.urls import path
from .views import OptimalRouteView, display_route

urlpatterns = [
    path('optimal-route/', OptimalRouteView.as_view(), name='optimal-route'),
    path('route_map/', display_route, name='route_map'),
]
