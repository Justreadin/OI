from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    app_env:str="development"
    secret_key:str="change-me-too"
    database_url:str="sqlite:///./opportunities.db"
    database_backend:str=""
    firebase_project_id:str=""
    google_application_credentials:str=""
    openai_api_key:str=""
    openai_model:str="gpt-4.1-mini"
    openai_classifier_model:str="gpt-6-luna"
    enable_ai_classification:bool=False
    scan_interval_minutes:int=30
    enable_scheduler:bool=True
    user_email:str="favour@payla.vip"
    brave_search_api_key:str=""
    brave_scan_interval_hours:int=24
    adzuna_app_id:str=""
    adzuna_app_key:str=""
    greenhouse_board_tokens:str=""
    ashby_board_names:str=""
    lever_sites:str=""
    company_seed_urls:str=""
    arbeitnow_enabled:bool=True
    jobicy_enabled:bool=True
    himalayas_enabled:bool=True
    weworkremotely_enabled:bool=True
    app_password:str=""
    enable_basic_auth:bool=False
    max_jobs_per_source:int=250
    model_config=SettingsConfigDict(env_file=".env",extra="ignore")
    @staticmethod
    def csv(v): return [x.strip() for x in (v or "").split(",") if x.strip()]
settings=Settings()
