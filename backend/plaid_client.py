import os
from dotenv import load_dotenv
from plaid.api import plaid_api
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid import ApiClient, Configuration, Environment

load_dotenv()

PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID")
PLAID_SECRET = os.getenv("PLAID_SECRET")
PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")

# Map env string to Plaid environment
ENV_MAP = {
    "sandbox": Environment.Sandbox,
    #"development": Environment.Development,
    "production": Environment.Production,
}

configuration = Configuration(
    host=ENV_MAP[PLAID_ENV],
    api_key={
        "clientId": PLAID_CLIENT_ID,
        "secret": PLAID_SECRET,
    },
)

api_client = ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

PLAID_PRODUCTS = [Products("transactions")]
PLAID_COUNTRY_CODES = [CountryCode("US")]
