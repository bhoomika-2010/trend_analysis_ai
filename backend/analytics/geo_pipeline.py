import sys
import os
from datetime import date
from database.db import get_db_connection
from serpapi import GoogleSearch

# Import SERPAPI_KEY from google_trends module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
try:
    from backend.scripts.google_trends import SERPAPI_KEY
except ImportError:
    SERPAPI_KEY = None

# Optional normalization helpers
try:
    import pycountry
except Exception:
    pycountry = None

try:
    from geopy.geocoders import Nominatim
    _GEOCODER = Nominatim(user_agent='trendanalysis_geo')
except Exception:
    _GEOCODER = None

_norm_cache = {}


def _normalize_country(country_str, city=None):
    """Normalize country name to a common printable form. If pycountry is
    available, try to match by name or alpha_2/alpha_3 codes. If not found and
    a `city` is provided and geopy is available, attempt reverse geocoding.
    Caches results in memory.
    """
    if not country_str and not city:
        return None
    key = (country_str or '').strip().lower() + '||' + (city or '').strip().lower()
    if key in _norm_cache:
        return _norm_cache[key]

    candidate = country_str or ''
    result = None
    if pycountry and candidate:
        # try common lookups
        try:
            # direct common name lookup
            c = pycountry.countries.get(name=candidate)
            if not c:
                # try lookup by common name or partial match
                for ctry in pycountry.countries:
                    if candidate.lower() in ctry.name.lower():
                        c = ctry
                        break
            if not c:
                # try alpha_2 or alpha_3
                c = pycountry.countries.get(alpha_2=candidate.upper()) or pycountry.countries.get(alpha_3=candidate.upper())
            if c:
                result = c.name
        except Exception:
            result = None

    # fallback: if geocoder available and no country matched, try to geocode city
    if not result and _GEOCODER and city:
        try:
            loc = _GEOCODER.geocode(city, exactly_one=True, language='en')
            if loc and hasattr(loc, 'raw'):
                addr = loc.raw.get('display_name') or ''
                # often display_name ends with 'Country'
                parts = [p.strip() for p in addr.split(',')]
                if parts:
                    result = parts[-1]
        except Exception:
            result = None

    # final fallback: return original string trimmed
    if not result:
        result = country_str.strip() if country_str else None

    _norm_cache[key] = result
    return result


def _parse_serpapi_geo_response(results):
    """Parse SerpAPI Google Trends geographic response and extract country/region data.
    Returns a list of dicts: [{'country': str, 'value': float, 'region': str, 'city': str}, ...]
    """
    candidates = []
    
    # Debug: Print the response structure to understand what we're getting
    print("\n=== DEBUG: SerpAPI Response Structure ===")
    print(f"Top-level keys: {list(results.keys())[:10]}")
    
    def _collect_from_list(arr, source_type='unknown'):
        """Helper to collect geographic data from a list of items."""
        for item in arr:
            if not isinstance(item, dict):
                continue
            # Try multiple possible keys for location name
            name = (item.get('geoName') or item.get('location') or item.get('region') or 
                   item.get('country') or item.get('name') or item.get('title') or 
                   item.get('geo'))
            # Try multiple possible keys for value
            val = (item.get('extracted_value') or item.get('value') or 
                  item.get('interest') or item.get('score'))
            
            if name and val is not None:
                try:
                    # Debug first few items
                    if len(candidates) < 3:
                        print(f"  Found item from {source_type}: name='{name}', value={val}, keys={list(item.keys())[:5]}")
                    
                    candidates.append({
                        'country': name,
                        'value': float(val),
                        'region': item.get('region') or None,
                        'city': item.get('city') or None,
                        'geoCode': item.get('geoCode') or item.get('coordinates') or None
                    })
                except (ValueError, TypeError) as e:
                    if len(candidates) < 3:
                        print(f"  Error parsing item: {e}, item={item}")
                    pass

    # Priority 1: interest_by_region (most reliable for countries)
    ib_region = results.get('interest_by_region')
    if ib_region:
        print(f"Found 'interest_by_region': type={type(ib_region)}")
        if isinstance(ib_region, list):
            _collect_from_list(ib_region, 'interest_by_region')
        elif isinstance(ib_region, dict):
            # Sometimes dict maps names->values
            for k, v in ib_region.items():
                try:
                    candidates.append({
                        'country': k,
                        'value': float(v),
                        'region': None,
                        'city': None,
                        'geoCode': None
                    })
                except (ValueError, TypeError):
                    pass

    # Priority 2: interest_by_country
    if not candidates:
        ib_country = results.get('interest_by_country')
        if ib_country:
            print(f"Found 'interest_by_country': type={type(ib_country)}")
            if isinstance(ib_country, list):
                _collect_from_list(ib_country, 'interest_by_country')
            elif isinstance(ib_country, dict):
                for k, v in ib_country.items():
                    try:
                        candidates.append({
                            'country': k,
                            'value': float(v),
                            'region': None,
                            'city': None,
                            'geoCode': None
                        })
                    except (ValueError, TypeError):
                        pass

    # Priority 3: Check for geoMapData (common SerpAPI structure)
    if not candidates:
        geo_map = results.get('geoMapData') or results.get('geo_map_data')
        if geo_map:
            print(f"Found 'geoMapData': type={type(geo_map)}")
            if isinstance(geo_map, list):
                _collect_from_list(geo_map, 'geoMapData')

    # Priority 4: interest_by_city (less preferred, but better than nothing)
    if not candidates:
        ib_city = results.get('interest_by_city')
        if ib_city:
            print(f"Found 'interest_by_city': type={type(ib_city)}")
            if isinstance(ib_city, list):
                _collect_from_list(ib_city, 'interest_by_city')

    # Fallback keys
    if not candidates:
        for key in ('by_country', 'geo', 'regions', 'region_interest', 'default'):
            arr = results.get(key)
            if arr:
                if isinstance(arr, dict):
                    # Check if it has geoMapData inside
                    geo_map = arr.get('geoMapData') or arr.get('geo_map_data')
                    if geo_map and isinstance(geo_map, list):
                        _collect_from_list(geo_map, f'{key}.geoMapData')
                        break
                elif isinstance(arr, list):
                    _collect_from_list(arr, key)
                    if candidates:
                        break

    # Final fallback: scan top-level for arrays of dicts that look like regions
    if not candidates:
        for k, v in results.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                # Heuristically check for value-like entries
                if any('value' in x or 'interest' in x or 'extracted_value' in x or 'geoName' in x for x in v[:3]):
                    _collect_from_list(v, f'top-level.{k}')
                    if candidates:
                        break

    print(f"=== Total candidates found: {len(candidates)} ===\n")
    return candidates


def enrich_geo_and_aggregate(keyword, days_back=None, platform_filter=None):
    """Fetch geographic data from Google Trends via SerpAPI for the given keyword
    and store it in the `geo_metrics` table. Uses current date for the metrics
    since Google Trends geographic data is typically a snapshot.

    Args:
        keyword: The keyword to analyze
        days_back: Ignored (kept for API compatibility, but Google Trends provides current snapshot)
        platform_filter: Ignored (kept for API compatibility, always uses 'Google Trends')

    Returns a summary dict: { 'success': bool, 'locations_found': n, 'upserted': m, ... }
    """
    if not SERPAPI_KEY or SERPAPI_KEY.startswith('YOUR'):
        return {'success': False, 'error': 'SERPAPI_KEY not configured'}

    conn = get_db_connection()
    if conn is None:
        return {'success': False, 'error': 'DB connection failed'}

    cursor = conn.cursor(dictionary=True)
    
    # Determine timeframe - use recent data for better geographic breakdown
    # Try multiple timeframes to get the best geographic data
    timeframes = ['today 12-m', 'today 3-m', 'now 7-d', 'today 5-y']
    
    geo_data = []
    last_exception = None
    
    for timeframe in timeframes:
        try:
            # Try with resolution=COUNTRY to ensure we get country-level data, not cities
            params = {
                'engine': 'google_trends',
                'q': [keyword],
                'api_key': SERPAPI_KEY,
                'hl': 'en',
                'data_type': 'GEO_MAP_0',  # Force geographic data, not time-series
                'date': timeframe,
                'resolution': 'COUNTRY',  # Explicitly request country-level data
                'tz': '420'
            }
            
            search = GoogleSearch(params)
            results = search.get_dict()
            
            if isinstance(results, dict) and results.get("error"):
                print(f"SerpApi GEO_MAP error for timeframe {timeframe}: {results['error']}")
                continue
            
            # Parse the geographic response
            candidates = _parse_serpapi_geo_response(results)
            
            if candidates:
                geo_data = candidates
                print(f"Successfully fetched {len(candidates)} geographic entries using timeframe: {timeframe}")
                # Print first few for debugging
                print(f"Sample data (first 5): {candidates[:5]}")
                break
                
        except Exception as e:
            print(f"SerpAPI request failed for timeframe {timeframe}: {e}")
            last_exception = e
            continue
    
    if not geo_data:
        error_msg = f"No geographic data returned from SerpAPI"
        if last_exception:
            error_msg += f": {last_exception}"
        conn.close()
        return {'success': False, 'error': error_msg, 'locations_found': 0, 'upserted': 0}
    
    try:
        # Use current date for the geographic snapshot data
        current_date = date.today()
        platform = 'Google Trends'
        
        # First, check if the table has the 'date' column
        cursor.execute("SHOW COLUMNS FROM geo_metrics LIKE 'date'")
        has_date_column = cursor.fetchone() is not None
        
        if not has_date_column:
            # Try without date column (in case table structure is different)
            upsert_q = """
                INSERT INTO geo_metrics (keyword, platform, country, region, city, metric)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    metric = VALUES(metric), 
                    region = VALUES(region), 
                    city = VALUES(city), 
                    created_at = CURRENT_TIMESTAMP
            """
            use_date = False
        else:
            # Use date column with backticks (MySQL reserved word)
            upsert_q = """
                INSERT INTO geo_metrics (keyword, platform, country, region, city, `date`, metric)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    metric = VALUES(metric), 
                    region = VALUES(region), 
                    city = VALUES(city), 
                    created_at = CURRENT_TIMESTAMP
            """
            use_date = True
        
        inserted = 0
        print(f"\n=== Processing {len(geo_data)} geographic entries ===")
        for item in geo_data:
            country_name = item.get('country')
            if not country_name:
                continue
            
            original_name = country_name
            
            # Normalize country name - this should handle variations like "South Korea" vs "Korea"
            norm_country = _normalize_country(country_name, city=item.get('city'))
            if norm_country:
                country_name = norm_country
                if original_name != norm_country and inserted < 5:
                    print(f"  Normalized: '{original_name}' -> '{norm_country}'")
            
            metric_value = item.get('value', 0.0)
            region = item.get('region')
            city = item.get('city')
            
            # Debug: Print first few insertions
            if inserted < 5:
                print(f"  [{inserted+1}] country='{country_name}', value={metric_value}, region={region}, city={city}")
            
            if use_date:
                cursor.execute(upsert_q, (
                    keyword,
                    platform,
                    country_name,
                    region,
                    city,
                    current_date,
                    metric_value
                ))
            else:
                cursor.execute(upsert_q, (
                    keyword,
                    platform,
                    country_name,
                    region,
                    city,
                    metric_value
                ))
            inserted += 1
        
        conn.commit()
        return {
            'success': True,
            'locations_found': len(geo_data),
            'upserted': inserted,
            'rows_processed': len(geo_data)
        }
        
    except Exception as e:
        conn.rollback()
        return {'success': False, 'error': str(e), 'locations_found': 0, 'upserted': 0}
    finally:
        cursor.close()
        conn.close()
