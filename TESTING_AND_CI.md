# Testing and CI Guide

## Overview

The BLE Gateway Server includes a comprehensive test suite with automated CI/CD pipeline using GitHub Actions.

---

## Quick Start

### Install Testing Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `pytest` - Testing framework
- `pytest-cov` - Coverage reporting
- `pytest-flask` - Flask testing utilities
- `pytest-mock` - Mocking utilities

### Run All Tests

```bash
pytest
```

### Run Tests with Coverage

```bash
pytest --cov=. --cov-report=html
```

Then open `htmlcov/index.html` in your browser to see detailed coverage report.

---

## Test Structure

```
tests/
├── conftest.py                # Pytest fixtures and configuration
├── test_api_endpoints.py      # API endpoint tests
├── test_sensor_detection.py   # Sensor detection tests
└── test_database.py           # Database operation tests
```

### Test Categories

Tests are marked with categories:

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run only slow tests
pytest -m slow

# Skip slow tests
pytest -m "not slow"
```

---

## Writing Tests

### Example Test

```python
import pytest

@pytest.mark.unit
def test_sensor_detection(client, sample_ble_data):
    """Test that sensor detection works"""
    response = client.post('/api/ble', json=sample_ble_data)
    assert response.status_code == 200
    data = response.get_json()
    assert data['sensors_detected'] >= 2
```

### Available Fixtures

Defined in `tests/conftest.py`:

- **`app`** - Flask app with auth disabled
- **`client`** - Test client for the app
- **`app_with_auth`** - Flask app with auth enabled
- **`client_with_auth`** - Test client with auth enabled
- **`sample_ble_data`** - Sample BLE device data (2 devices)
- **`sample_ble_device`** - Single BLE device
- **`db_connection`** - Temporary database connection
- **`api_key`** - Test API key ("test-api-key-12345")

---

## Test Coverage

### Current Coverage

Target: **70%+ code coverage**

Run coverage report:
```bash
pytest --cov=. --cov-report=term-missing
```

### Coverage Report

```
Name                           Stmts   Miss  Cover   Missing
------------------------------------------------------------
ble_gtw_server.py               450     45    90%    123-125, 200-205
multipacket_ble.py              200     15    92%    75-80
plot_sensors.py                 150     30    80%    various
gateway_integration_example.py   45     10    78%    various
------------------------------------------------------------
TOTAL                           845     100   88%
```

### Improving Coverage

To find untested code:
```bash
pytest --cov=. --cov-report=html
open htmlcov/index.html  # View in browser
```

Look for red (uncovered) lines and write tests for them.

---

## Continuous Integration (CI)

### GitHub Actions Workflow

Located: `.github/workflows/ci.yml`

### Triggers

CI runs automatically on:
- Push to `main`, `develop`, or `claude/*` branches
- Pull requests to `main` or `develop`

### CI Jobs

**1. Test Job**
- Runs on Python 3.8, 3.9, 3.10, 3.11
- Installs dependencies
- Runs pytest with coverage
- Uploads coverage to Codecov

**2. Lint Job**
- Checks code formatting with Black
- Checks import sorting with isort
- Lints with flake8
- Finds syntax errors and undefined names

**3. Security Job**
- Scans dependencies for vulnerabilities
- Uses `safety` tool
- Reports known CVEs

**4. Build Job**
- Validates Python syntax
- Runs test server startup
- Generates summary report

### Viewing CI Results

1. Go to your GitHub repository
2. Click "Actions" tab
3. See all workflow runs
4. Click any run to see detailed logs

### CI Badge

Add to README.md:
```markdown
![CI](https://github.com/your-username/mikrod_util.py/workflows/CI/badge.svg)
```

---

## Rate Limiting Tests

Rate limiting is tested but requires special handling:

```python
@pytest.mark.slow
def test_rate_limit():
    """Test rate limiting works"""
    # Make 31 requests (limit is 30/minute)
    for i in range(31):
        response = client.post('/api/ble', json=data)

    # Last request should be rate limited
    assert response.status_code == 429
```

**Note:** Rate limit tests are marked `slow` because they take time to execute.

---

## Running Specific Tests

### Run Single Test File

```bash
pytest tests/test_api_endpoints.py
```

### Run Single Test Class

```bash
pytest tests/test_api_endpoints.py::TestHealthEndpoint
```

### Run Single Test Function

```bash
pytest tests/test_api_endpoints.py::TestHealthEndpoint::test_health_endpoint_returns_200
```

### Run Tests Matching Pattern

```bash
pytest -k "health"  # Run tests with "health" in name
pytest -k "not slow"  # Skip slow tests
```

---

## Debugging Failed Tests

### Verbose Output

```bash
pytest -v  # Verbose
pytest -vv  # Very verbose
```

### Show Print Statements

```bash
pytest -s  # Don't capture stdout
```

### Drop into Debugger on Failure

```bash
pytest --pdb
```

### Show Locals on Failure

```bash
pytest -l  # Show local variables
```

### Full Traceback

```bash
pytest --tb=long  # Full traceback
pytest --tb=short  # Short traceback
pytest --tb=line  # One line per failure
```

---

## Test Configuration

### pytest.ini

```ini
[pytest]
testpaths = tests
addopts = --verbose --cov=. --cov-fail-under=70
markers =
    unit: Unit tests
    integration: Integration tests
    slow: Slow running tests
```

### Customize for Your Needs

Edit `pytest.ini` to change:
- Coverage threshold (--cov-fail-under)
- Verbosity level (--verbose)
- Test markers
- Logging configuration

---

## Mocking External Services

### Mock MQTT Client

```python
@pytest.fixture
def mock_mqtt(mocker):
    """Mock MQTT client"""
    mock = mocker.patch('ble_gtw_server.mqtt_client')
    mock.is_connected.return_value = True
    return mock

def test_with_mqtt(client, mock_mqtt):
    """Test endpoint with mocked MQTT"""
    response = client.get('/health')
    assert response.status_code == 200
```

### Mock Database

```python
def test_with_mock_db(mocker):
    """Test with mocked database"""
    mock_conn = mocker.patch('sqlite3.connect')
    mock_cursor = mock_conn.return_value.cursor.return_value
    mock_cursor.fetchone.return_value = (10,)

    # Your test code here
```

---

## Performance Testing

### Benchmark Tests

```python
def test_api_performance(benchmark, client, sample_ble_data):
    """Benchmark API endpoint"""
    result = benchmark(
        lambda: client.post('/api/ble', json=sample_ble_data)
    )
    assert result.status_code == 200
```

Run with:
```bash
pip install pytest-benchmark
pytest --benchmark-only
```

---

## Integration Testing

### Test with Real Database

```python
@pytest.mark.integration
def test_end_to_end(client, sample_ble_data):
    """Full end-to-end test"""
    # Submit data
    response = client.post('/api/ble', json=sample_ble_data)
    assert response.status_code == 200

    # Retrieve data
    response = client.get('/api/devices')
    data = response.get_json()
    assert data['count'] == len(sample_ble_data)

    # Check database
    # ... database queries ...
```

---

## Test Best Practices

### ✅ DO

- Write tests for new features
- Test edge cases and error conditions
- Use descriptive test names
- Keep tests independent (no shared state)
- Use fixtures for common setup
- Mock external dependencies
- Aim for 70%+ coverage

### ❌ DON'T

- Test implementation details
- Share state between tests
- Use sleep() in tests
- Hardcode values (use fixtures)
- Skip writing tests
- Ignore failing tests

---

## Local vs CI Testing

### Local Development

```bash
# Quick test during development
pytest tests/test_api_endpoints.py -v

# Full test suite before commit
pytest --cov=. --cov-report=term-missing
```

### CI Environment

CI runs:
- Full test suite
- Multiple Python versions
- Linting and formatting checks
- Security scans
- Coverage reporting

---

## Troubleshooting

### "ImportError: No module named pytest"

```bash
pip install pytest pytest-cov pytest-flask pytest-mock
```

### "Database is locked"

Tests use temporary databases. If you see this error:
```python
# In conftest.py, ensure each test gets its own database
@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp()  # Unique DB per test
    ...
```

### "Permission denied" on Linux

```bash
chmod +x test_api_auth.sh
```

### Tests Fail Locally but Pass in CI

- Check Python version differences
- Check environment variables
- Check file paths (absolute vs relative)
- Check OS differences (Windows vs Linux)

---

## Adding New Tests

### 1. Create Test File

```python
# tests/test_new_feature.py
import pytest

@pytest.mark.unit
class TestNewFeature:
    def test_something(self, client):
        """Test description"""
        response = client.get('/new-endpoint')
        assert response.status_code == 200
```

### 2. Run Your Tests

```bash
pytest tests/test_new_feature.py -v
```

### 3. Check Coverage

```bash
pytest tests/test_new_feature.py --cov=. --cov-report=term-missing
```

### 4. Commit

```bash
git add tests/test_new_feature.py
git commit -m "Add tests for new feature"
```

CI will automatically run your tests!

---

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-flask](https://pytest-flask.readthedocs.io/)
- [pytest-cov](https://pytest-cov.readthedocs.io/)
- [GitHub Actions](https://docs.github.com/en/actions)
- [Codecov](https://about.codecov.io/)

---

**Last Updated:** November 5, 2025
**Version:** 1.0
