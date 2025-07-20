import pytest
from app.providers.ranks import assign_ranks
from app.providers.providers import PROVIDERS


def test_assign_ranks():
    # ensure all provider ranks are assigned correctly
    assign_ranks(PROVIDERS)
