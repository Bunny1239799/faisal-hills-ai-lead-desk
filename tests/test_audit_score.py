import csv
import pytest
from pathlib import Path
from tools.audit_score import score_audit_sheet

@pytest.fixture
def dummy_audit_csv(tmp_path):
    csv_file = tmp_path / "audit_sheet.csv"
    fieldnames = [
        'sample_type', 'listing_id', 'side', 'category', 'block_code', 
        'size_marla', 'price_pkr', 'plot_no', 'raw_text', 'reason_code', 
        'block_ok', 'plot_ok', 'size_ok', 'price_ok'
    ]
    with open(csv_file, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        # Write 10 rows with 100% pass for block and price
        for i in range(10):
            writer.writerow({
                'sample_type': 'parsed_sell_plot',
                'listing_id': str(i),
                'side': 'sell',
                'category': 'plot',
                'block_code': 'A',
                'size_marla': 5.0,
                'price_pkr': 5000000,
                'plot_no': '1',
                'raw_text': 'test',
                'reason_code': '',
                'block_ok': '1',
                'plot_ok': '1',
                'size_ok': '1',
                'price_ok': '1'
            })
    return csv_file

def test_audit_score_pass(dummy_audit_csv, monkeypatch):
    result = score_audit_sheet(csv_path=dummy_audit_csv)
    assert result['passed'] is True
    assert result['accuracies']['block_ok'] == 1.0
    assert result['accuracies']['price_ok'] == 1.0

def test_audit_score_fail(tmp_path, monkeypatch):
    csv_file = tmp_path / "audit_sheet.csv"
    fieldnames = [
        'sample_type', 'listing_id', 'side', 'category', 'block_code', 
        'size_marla', 'price_pkr', 'plot_no', 'raw_text', 'reason_code', 
        'block_ok', 'plot_ok', 'size_ok', 'price_ok'
    ]
    with open(csv_file, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        # Low accuracy rows
        for i in range(10):
            writer.writerow({
                'sample_type': 'parsed_sell_plot',
                'listing_id': str(i),
                'side': 'sell',
                'category': 'plot',
                'block_code': 'A',
                'size_marla': 5.0,
                'price_pkr': 5000000,
                'plot_no': '1',
                'raw_text': 'test',
                'reason_code': 'MISSING_PRICE',
                'block_ok': '0' if i < 5 else '1',
                'plot_ok': '0',
                'size_ok': '0',
                'price_ok': '0' if i < 5 else '1'
            })
    result = score_audit_sheet(csv_path=csv_file)
    assert result['passed'] is False
    assert result['accuracies']['block_ok'] == 0.5
    assert result['accuracies']['price_ok'] == 0.5
