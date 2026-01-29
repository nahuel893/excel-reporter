"""
Core module - Shared functionality across all reports.

Contains:
- DataLoader: Database access
- ExcelWriter: Excel file generation
- Base processing utilities
"""
from src.core.data_loader import DataLoader
from src.core.excel_writer import generar_excel

__all__ = ["DataLoader", "generar_excel"]
