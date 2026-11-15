import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Job
from app.sources import upsert, _PENDING_URLS

class SourceTests(unittest.TestCase):
    def test_same_url_is_deduplicated_within_one_scan_before_commit(self):
        engine=create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session=sessionmaker(bind=engine,autoflush=False)
        db=Session()
        try:
            _PENDING_URLS.clear()
            first=upsert(db,"Feed A","1","Example","Product Manager","Remote","Remote role","https://example.org/jobs/1")
            second=upsert(db,"Feed B","2","Example","Product Manager","Remote","Remote role","https://example.org/jobs/1")
            db.commit()
            self.assertEqual(first,1)
            self.assertEqual(second,0)
            self.assertEqual(db.query(Job).count(),1)
        finally:
            db.close();engine.dispose();_PENDING_URLS.clear()

if __name__=="__main__":unittest.main()

class BraveDiscoveryTests(unittest.TestCase):
    def test_news_filter_rejects_general_company_news(self):
        from app.sources import _brave_listing_signal
        self.assertFalse(_brave_listing_signal("Company raises Series B", "Funding announcement"))
        self.assertTrue(_brave_listing_signal("Applications open for 2027 research internship", "Apply now"))

    def test_context_discovery_uses_extracted_chunks_and_source_metadata(self):
        import asyncio
        from unittest.mock import patch
        from app import sources
        from app.database import Base
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        payload = {
            "grounding": {"generic": [{
                "url": "https://careers.example.org/research-intern",
                "title": "Research Internship",
                "snippets": ["Applications are open for a research internship. Applicants based in Nigeria may apply."]
            }]},
            "sources": {"https://careers.example.org/research-intern": {
                "hostname": "careers.example.org", "age": ["", "", "", "2026-11-14T12:00:00Z"]
            }}
        }
        class FakeResponse:
            def raise_for_status(self):
                return None
            def json(self):
                return payload
        class FakeClient:
            all_calls = []
            def __init__(self, *args, **kwargs):
                self.calls = []
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def get(self, url, params=None):
                self.calls.append((url, params))
                type(self).all_calls.append((url, params))
                return FakeResponse()
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine, autoflush=False)()
        try:
            sources._PENDING_URLS.clear()
            FakeClient.all_calls.clear()
            with patch.object(sources.settings, "brave_search_api_key", "test-key"), \
                 patch.object(sources.httpx, "AsyncClient", FakeClient):
                count = asyncio.run(sources.brave_llm_context_discovery(db))
            db.commit()
            self.assertEqual(count, 1)
            self.assertTrue(FakeClient.all_calls)
            self.assertTrue(all(call[1].get("country") == "ALL" for call in FakeClient.all_calls))
            row = db.query(Job).filter_by(url="https://careers.example.org/research-intern").first()
            self.assertIsNotNone(row)
            self.assertEqual(row.source, "Brave LLM context")
            self.assertIn("Applicants based in Nigeria", row.description)
        finally:
            db.close(); engine.dispose(); sources._PENDING_URLS.clear()

    def test_brave_cooldown_is_configurable_and_clamped(self):
        from app.sources import settings
        self.assertTrue(hasattr(settings, "brave_scan_interval_hours"))
        self.assertEqual(settings.brave_scan_interval_hours, 24)


class MyJobMagTests(unittest.TestCase):
    def test_listing_parser_extracts_job_links_and_ignores_category_navigation(self):
        from bs4 import BeautifulSoup
        from app.sources import _myjobmag_listing_cards
        html = """
        <html><body>
          <a href="/internship/">Internship Jobs</a>
          <article class="job-listing">
            <h2><a href="/job/business-analysis-intern-at-example/">Business Analysis Intern at Example Ltd</a></h2>
            <p>Support research and analysis. Date Posted: 14 November 2026 Lagos</p>
          </article>
        </body></html>
        """
        cards = list(_myjobmag_listing_cards(BeautifulSoup(html, "html.parser"), "https://www.myjobmag.com/internship/"))
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["title"], "Business Analysis Intern at Example Ltd")
        self.assertEqual(cards[0]["url"], "https://www.myjobmag.com/job/business-analysis-intern-at-example/")

    def test_metadata_extracts_company_location_and_date(self):
        from app.sources import _myjobmag_metadata
        company, location, published = _myjobmag_metadata(
            "Business Analysis Intern at Example Ltd Date Posted: 14 November 2026 Lagos",
            "Business Analysis Intern at Example Ltd")
        self.assertEqual(company, "Example Ltd")
        self.assertEqual(location, "Lagos")
        self.assertEqual(published, "14 November 2026")
