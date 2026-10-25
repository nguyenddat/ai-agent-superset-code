from flask_appbuilder import Model
from sqlalchemy import Column, ForeignKey, Integer, Text
from superset.models.helpers import AuditMixinNullable


class BusinessCanvas(AuditMixinNullable, Model):
    """Business-view canvas of one Superset database: the grid cells of each business domain and table.

    ``layout`` is JSON: ``{"domains": [{"key", "header": [col, row], "cells": [[col, row], ...]}], "tables":
    {"<dataset id>": [col, row]}}``. It only records positions; domain membership stays in the domain tables.
    """

    __tablename__ = "text_to_bi_business_canvas"
    __table_args__ = ({"extend_existing": True},)

    database_id = Column(Integer, ForeignKey("dbs.id", ondelete="CASCADE"), primary_key=True)
    layout = Column(Text, nullable=False)
