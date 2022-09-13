#!/usr/bin/env python3

"""
Python script to publish missing person posters on a FB page.
"""

import dataclasses
import datetime
import logging
import os
import urllib.parse
import zoneinfo
from typing import Any, Optional

import requests
import urllib3
import urllib3.exceptions

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REQUEST_TIMEOUT = 60 * 2
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")


class ExtraviadosMxApiException(Exception):
    """Use this exception for raising errors related with the Extraviados MX API."""


@dataclasses.dataclass
class Mpp:
    """Represents the missing person poster provided by the Extraviados MX API."""

    id: str
    slug: str
    mp_name: str
    mp_height: Optional[int]
    mp_weight: Optional[int]
    mp_physical_build: str
    mp_complexion: str
    mp_sex: str
    mp_dob: Optional[datetime.date]
    mp_age_when_disappeared: int
    mp_eyes_description: str
    mp_hair_description: str
    mp_outfit_description: str
    mp_identifying_characteristics: str
    circumstances_behind_dissapearance: str
    missing_from: str
    missing_date: Optional[datetime.date]
    found: bool
    alert_type: str
    po_state: str
    po_post_url: str
    po_post_publication_date: Optional[datetime.date]
    po_poster_url: str
    is_multiple: bool
    updated_at: Optional[datetime.datetime]
    created_at: Optional[datetime.datetime]

    @classmethod
    def from_api_dict(cls, api_dict: dict[str, Any]) -> "Mpp":
        """
        Returns an instance of this class from a dictionary provided by parsing the JSON
        response from Extraviados MX API.
        """
        try:
            raw_mp_dob = api_dict["mp_dob"]
            raw_missing_date = api_dict["missing_date"]
            raw_po_post_publication_date = api_dict["po_post_publication_date"]
            raw_updated_at = api_dict["updated_at"]
            raw_created_at = api_dict["created_at"]
        except KeyError as ex:
            raise ExtraviadosMxApiException(
                f"provided dict did not contain the key {ex}"
            ) from ex
        mp_dob = (
            None
            if raw_mp_dob is None
            else datetime.datetime.strptime(raw_mp_dob, "%Y-%m-%d").date()
        )
        missing_date = (
            None
            if raw_missing_date is None
            else datetime.datetime.strptime(raw_missing_date, "%Y-%m-%d").date()
        )
        po_post_publication_date = (
            None
            if raw_po_post_publication_date is None
            else datetime.datetime.strptime(
                raw_po_post_publication_date, "%Y-%m-%d"
            ).date()
        )
        updated_at = (
            None
            if raw_updated_at is None
            else datetime.datetime.fromisoformat(raw_updated_at)
        )
        created_at = (
            None
            if raw_created_at is None
            else datetime.datetime.fromisoformat(raw_created_at)
        )
        mpp = cls(**api_dict)
        mpp.mp_dob = mp_dob
        mpp.missing_date = missing_date
        mpp.po_post_publication_date = po_post_publication_date
        mpp.updated_at = updated_at
        mpp.created_at = created_at
        return mpp

    def get_absolute_url(self) -> str:
        return f"https://extraviados.mx/{self.slug}/"

    def get_facebook_post_url(self) -> str:
        return self.get_absolute_url() + "facebook-post/"


@dataclasses.dataclass
class RetrieveMppsApiBody:
    """
    Represents the response given by the endpoint https://extraviados.mx/api/v1/mpps/
    """

    next: Optional[str]
    previous: Optional[str]
    count: int
    results: list[Mpp]

    @classmethod
    def from_api_dict(cls, api_dict: dict[str, Any]) -> "RetrieveMppsApiBody":
        """
        Returns an instance of this class from a dictionary provided by parsing the JSON
        response given by the endpoint https://extraviados.mx/api/v1/mpps/.
        """
        try:
            results = api_dict["results"]
            next_ = api_dict["next"]
            previous = api_dict["previous"]
            count = api_dict["count"]
        except KeyError as ex:
            raise ExtraviadosMxApiException(
                f"provided dict did not contain the key {ex}"
            ) from ex
        results = [Mpp.from_api_dict(result) for result in results]
        return cls(
            next=next_,
            previous=previous,
            count=count,
            results=results,
        )


def _retrieve_mpps_by_updated_at_date(url: str) -> RetrieveMppsApiBody:
    res = requests.get(url, timeout=REQUEST_TIMEOUT)
    if res.status_code != 200:
        raise ExtraviadosMxApiException(f"{res.url} returned status {res.status_code}")
    try:
        body = res.json()
    except requests.exceptions.JSONDecodeError as ex:
        raise ExtraviadosMxApiException(
            f"unable to parse JSON returned by {res.url}"
        ) from ex
    return RetrieveMppsApiBody.from_api_dict(body)


def retrieve_mpps_by_updated_at_date(
    updated_at_after: datetime.date,
    updated_at_before: datetime.date,
    po_state: Optional[str] = None,
    extraviadosmx_endpoint_url: Optional[str] = None,
) -> list[Mpp]:
    """Retrieves the missing person posters from the Extraviados MX API.

    It will retrieve those mpps whose update_at field in after updated_at_after and
    before updated_at_before.

    You can change the Extraviados MX API endpoint (https://extraviados.mx) by
    providing the parameter extraviadosmx_endpoint_url.
    """
    if extraviadosmx_endpoint_url is None:
        extraviadosmx_endpoint_url = "https://extraviados.mx"
    params = {
        "updated_at_after": updated_at_after.isoformat(),
        "updated_at_before": updated_at_before.isoformat(),
    }
    if po_state is not None:
        params["po_state"] = po_state
    url = f"{extraviadosmx_endpoint_url}/api/v1/mpps/?" + urllib.parse.urlencode(params)
    api_res = _retrieve_mpps_by_updated_at_date(url)
    records = api_res.results
    while api_res.next is not None:
        api_res = _retrieve_mpps_by_updated_at_date(api_res.next)
        records += api_res.results
    return records


def post_photo(mpp: Mpp) -> dict:
    post_content_res = requests.get(mpp.get_facebook_post_url(), timeout=10)
    post_content_res.raise_for_status()
    photo_res = requests.get(mpp.po_poster_url, stream=True, verify=False, timeout=10)
    photo_res.raise_for_status()
    params = {
        "message": post_content_res.text,
        "access_token": FB_PAGE_ACCESS_TOKEN,
    }
    files = {
        "data": photo_res.raw,
    }
    fb_res = requests.post(
        f"https://graph.facebook.com/{FB_PAGE_ID}/photos", params=params, files=files
    )
    fb_res.raise_for_status()
    return fb_res.json()


def post_link(mpp: Mpp) -> dict:
    post_content_res = requests.get(mpp.get_facebook_post_url())
    post_content_res.raise_for_status()
    params = {
        "message": post_content_res.text,
        "link": mpp.get_absolute_url(),
        "access_token": FB_PAGE_ACCESS_TOKEN,
    }
    fb_res = requests.post(
        f"https://graph.facebook.com/{FB_PAGE_ID}/feed", params=params
    )
    fb_res.raise_for_status()
    return fb_res.json()


def config_logging(logfile: Optional[str]):
    """Configures the logging of this program."""
    logging.basicConfig(
        filename=logfile or None,
        encoding="utf-8",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%Y/%m/%d %I:%M:%S %p",
    )
    logging.captureWarnings(True)


def main():
    if FB_PAGE_ID is None:
        raise EnvironmentError("FB_PAGE_ID environment variable is not set")
    if FB_PAGE_ACCESS_TOKEN is None:
        raise EnvironmentError("FB_PAGE_ACCESS_TOKEN environment variable is not set")
    config_logging(None)
    america_mexico_city_tz = zoneinfo.ZoneInfo("America/Mexico_City")
    now = datetime.datetime.now(tz=america_mexico_city_tz)
    fifteen_min = datetime.timedelta(minutes=15)
    fifteen_min_ago = now - fifteen_min
    mpps = retrieve_mpps_by_updated_at_date(fifteen_min_ago, now)
    mpps_count = len(mpps)
    logging.info(
        "creating FB post for %s missing person posters updated after %s and before %s",
        mpps_count,
        fifteen_min_ago.isoformat(),
        now.isoformat(),
    )
    for mpp in mpps:
        logging.info("processing %s", mpp.mp_name.upper())
        try:
            response = post_photo(mpp)
            logging.info("photo post created, response: %s", response)
        except Exception:
            logging.exception("unable to create FB photo post for %s", mpp.mp_name)
            try:
                response = post_link(mpp)
                logging.info("link post created, response: %s", response)
            except Exception as ex:
                logging.exception("unable to create FB link post for %s", mpp.mp_name)
                raise ex from ex


if __name__ == "__main__":
    main()
