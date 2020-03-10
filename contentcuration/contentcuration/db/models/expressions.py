from django.db.models import Q
from django.db.models.sql.where import WhereNode


class WhenQ(Q):
    """
    Class that allows for defining conditions with expressions and using them in WHEN expressions
    that accept a Q object

    Example:
        queryset.annotate(some_thing=Case(When(condition=QExpression(BoolExpr(...)), then=...)))
    """
    def resolve_expression(self, *args, **kwargs):
        return WhereNode([child.resolve_expression(*args, **kwargs) for child in self.children])
