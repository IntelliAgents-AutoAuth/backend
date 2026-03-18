import requests
import json

BASE_URL = "http://localhost:8000/api/v1"

def get_token():
    url = f"{BASE_URL}/auth/login"
    data = {
        "username": "sai@example.com",
        "password": "test123"
    }
    response = requests.post(url, json=data)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        print(f"Failed to login: {response.text}")
        return None

def test_full_details(case_id):
    token = get_token()
    if not token:
        return

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/cases/{case_id}/full-details"
    
    print(f"Fetching full details for case: {case_id}")
    response = requests.get(url, headers=headers)
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        details = response.json()
        print("Success! Response structure:")
        print(json.dumps({k: "present" if v else "missing" for k, v in details.items()}, indent=2))
        
        # Check for expected keys
        expected_keys = ["case", "extracted_data", "ehr"]
        for key in expected_keys:
            if key in details:
                print(f"  [OK] '{key}' is present")
            else:
                print(f"  [FAIL] '{key}' is missing")
    else:
        print(f"Error: {response.text}")

if __name__ == "__main__":
    # We'll try to find a case ID first if one isn't provided
    token = get_token()
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        cases_response = requests.get(f"{BASE_URL}/cases", headers=headers)
        if cases_response.status_code == 200:
            cases = cases_response.json()
            if cases:
                test_full_details(cases[0]["case_id"])
            else:
                print("No cases found to test with.")
        else:
            print(f"Failed to fetch cases: {cases_response.text}")
