import argparse
import csv
import json
import os
import pathlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zipfile import BadZipfile, ZipFile

import requests
from fastkml import geometry, kml
from fastkml.features import Placemark
from fastkml.containers import Folder
from pygeoif import MultiLineString
from pygeoif.geometry import Point

import sidc

DATA_REPO_API_URL="https://api.github.com/repos/owlmaps/UAControlMapBackups/contents/"


class MapData:

    def __init__(self):
        self.data = {
            "timeline": {},
            "unit_map": {},
            "fortifications": [],
            "dragon_teeth": [],
        }
        self.unit_count = {}
        self.wanted_size = 0
        self.geolocations = {}
        self.base_date_key = ""
        self.dates = []
        self.unit_check = {}
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Accept-Encoding": "*",
            "Connection": "keep-alive",
        }

    def _request(self, url, content="raw"):

        is_success = False
        for _ in range(5):
            try:
                r = self.session.get(url, timeout=20)
                r.raise_for_status()
                is_success = True
                break
            except requests.exceptions.Timeout:
                print("The request timed out")
                continue
            except requests.exceptions.RequestException as e:
                print("An error occurred:")
                print(e.args[0])
                continue

        if not is_success:
            return None

        if content == "json":
            return r.json()
        if content == "text":
            return r.text

        return r.content

    def add_unit_to_map(self, unit):

        # generate a new key and add unit to map
        # and update unit_names check list
        new_unit_key = len(self.data["unit_map"].keys()) + 1
        self.data["unit_map"][new_unit_key] = {"n": unit["n"], "s": unit["s"]}
        # update the unit check dict
        self.unit_check[unit["n"]] = new_unit_key

    # pylint: disable-msg=too-many-locals
    def get_units_and_count(self, kml_root):
        data = {
            "units": {"ru": [], "ua": []},
            "count": {"ru": 0, "ua": 0},
        }
        ru_unit_folder_keys = ["Russian Unit Positions"]
        ua_unit_folder_keys = ["Ukrainian Unit Positions"]
        unit_folder = {"ru": [], "ua": []}

        for feature in kml_root.features:
            if isinstance(feature, Folder):
                if feature.name in ru_unit_folder_keys:
                    unit_folder["ru"].append(feature)
                if feature.name in ua_unit_folder_keys:
                    unit_folder["ua"].append(feature)

        for side, folders in unit_folder.items():
            # print(side)
            for folder in folders:
                # print(folder.name)
                data["count"][side] += len(list(folder.features))
                for unit in folder.features:

                    # print(f'{unit.name} -> {type(unit)} -> {type(unit.geometry)}')

                    # ignore all units that are not placemarks
                    # or where their geometry is not a point
                    if not isinstance(unit, Placemark):
                        continue
                    if not isinstance(unit.geometry, Point):
                        continue

                    # print(f'{unit.name} -> {type(unit)}')

                    if unit.name not in self.unit_check:
                        unit_map_data = {"n": unit.name, "s": side}
                        self.add_unit_to_map(unit_map_data)

                    unit_id = self.unit_check[unit.name]

                    lon = unit.geometry.coords[0][0] # type: ignore
                    lat = unit.geometry.coords[0][1] # type: ignore
                    unit_data = [unit_id, [lon, lat]]
                    data["units"][side].append(unit_data)

        return data

    def get_fortifications(self, kml_root):
        # print('get_fortifications()')
        areas_key = "Important Areas"
        fortifications_key = "Fortifications"
        dragon_teeth_key = "Dragon Teeth"
        areas = None
        fortifications = None
        dragon_teeth = None

        for feature in kml_root.features:
            if isinstance(feature, Folder):
                if feature.name == areas_key:
                    areas = feature
        if areas is None:
            print("no areas folder")
            return
        

        fortifications = []
        dragonteeth = []

        for feature in areas.features:
            if isinstance(feature, Placemark):
                if feature.name.startswith("Trenches") or feature.name.startswith("Fortifications"):
                    fortifications.append(feature)
                if feature.name.startswith("Dragon"):
                    dragonteeth.append(feature)

        # print(f'fortifications: {fortifications}')
        # print(f'dragonteeths: {dragonteeth}')

        for fortification in fortifications:
            # print('fortification loop')
            # print(type(fortification.geometry))
            if isinstance(fortification.geometry, MultiLineString):
                # print('- mls')
                for geom in fortification.geometry.geoms:
                    coords = []
                    for c in geom.coords: # type: ignore
                        coords.append([c[1], c[0]])
                    self.data["fortifications"].append(coords)

        for dgt in dragonteeth:
            if isinstance(dgt.geometry, MultiLineString):
                for geom in dgt.geometry.geoms:
                    coords = []
                    for c in geom.coords: # type: ignore
                        coords.append([c[1], c[0]])
                    self.data["dragon_teeth"].append(coords)

    def get_frontline(self, kml_root):
        data = []  # list of coordinates
        frontline_key = "Frontline"
        frontline_folder = None

        # frontline folder
        for feature in kml_root.features:
            if isinstance(feature, Folder):
                if feature.name == frontline_key:
                    frontline_folder = feature

        # frotline data
        if frontline_folder is not None:
            for feature in frontline_folder.features:
                if feature.name == frontline_key:
                    if isinstance(feature, Placemark):
                        coords = feature.geometry.coords # type: ignore
                        for c in coords:
                            data.append([c[1], c[0]])

        return data

    def process_kmz(self, item):

        # init data set
        data = {
            "date_key": item["real_data_date"],
            "unit_count": {"ru": 0, "ua": 0},
            "units": {"ru": [], "ua": []},
            "frontline": [],
        }

        # request remote file
        file_name = f'./tmp/{item["name"]}'
        content = self._request(item["url"])

        # some checks
        if content is None:
            data["bad_data"] = True
            return data

        # write kmz file to tmp dir
        with open(file_name, mode="wb") as f:
            f.write(content) # type: ignore

        # unzip the kmz and read the doc.kml file
        try:
            with ZipFile(file_name) as zf:
                # open doc
                with zf.open("doc.kml") as f:
                    doc = f.read()
        except BadZipfile:
            print("bad zipfile")
            # remove tmp file
            if os.path.exists(file_name):
                os.remove(file_name)
            data["bad_data"] = True
            return data

        # parse kml
        # k = kml.KML()
        # k.from_string(doc)

        k = kml.KML.from_string(doc)

        # get root
        kml_doc = list(k.features)
        kml_root = kml_doc[0]

        # get units & count
        unit_data = self.get_units_and_count(kml_root)
        # print(unit_data)
        data["unit_count"] = unit_data["count"]
        data["units"] = unit_data["units"]

        # get frontline data
        frontline_data = self.get_frontline(kml_root)
        data["frontline"] = frontline_data

        # if latest dataset, get all:
        # + fortifications
        if item["is_latest"]:
            self.base_date_key = item["real_data_date"]
            self.get_fortifications(kml_root)

        # remove tmp file
        if os.path.exists(file_name):
            os.remove(file_name)

        # fnally, return processed kmz data
        return data

    def get_kmz_list(self):

        # get json file listing
        file_list_json = self._request(DATA_REPO_API_URL, "json")

        # sub method to filter all kmz files
        def filter_kmz(item):
            if (
                item["type"] == "file"
                and ".kmz" in item["path"]
                and not "latest.kmz" in item["path"]
            ):
                return True
            return False

        # apply filter kmz method
        kmz_list = list(filter(filter_kmz, file_list_json)) # type: ignore

        # sub method to reoganize the data object
        def prepare_data(item):
            date_string = item["name"].split("_")[0]
            return {
                "file_date_string": date_string,
                "real_data_date": self.substract_day(date_string, out_format="%Y%m%d"),
                "name": item["name"],
                "url": item["download_url"],
                "is_latest": False,
            }

        # apply prepare data method
        data_list = list(map(prepare_data, kmz_list))

        # return final data
        return data_list

    def substract_day(self, date_key, in_format="%y%m%d", out_format="%y%m%d"):
        delta = timedelta(days=1)  # 1 day timedelta
        curdate = datetime.strptime(date_key, in_format)
        fixed_date = curdate - delta
        fixed_date_key = fixed_date.strftime(out_format)
        return fixed_date_key

    def generate_date_range_list(self, data_list):

        # extract the real data dates into a list
        dates_list = list(map(lambda x: x["real_data_date"], data_list))

        # find min and max date
        min_date = min(dates_list)
        max_date = max(dates_list)

        # format min & max date
        start = datetime.strptime(min_date, "%Y%m%d")
        end = datetime.strptime(max_date, "%Y%m%d")

        # define time delta (1 day)
        delta = timedelta(days=1)

        # init dates list
        dates = []

        # build date list with a step of 1 day
        while start <= end:
            dates.append(start.strftime("%Y%m%d"))
            start += delta

        # return date range list
        return dates

    def init_data(self, dates):
        # init an empty data set for each date in the full date range
        for date_str in dates:
            self.data["timeline"][date_str] = {
                "unit_count": {"ru": 0, "ua": 0},
                "units": {"ru": [], "ua": []},
                "frontline": [],
            }

    def write_count_csv(self, dates):
        with open("unit_count.csv", "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            field = ["date", "ru", "ua"]
            writer.writerow(field)
            for date_str in dates:
                s = date_str.replace("-", "")[2:]
                item = self.unit_count[s]
                writer.writerow([s, item["ru"], item["ua"]])

    def save_data(self):
        base_data = {
            "date": self.base_date_key,
            "unit_map": self.data["unit_map"],
            "dates": self.dates,
            "fortifications": self.data["fortifications"],
            "dragon_teeth": self.data["dragon_teeth"],
        }

        with open("./data/base.json", "w", encoding="utf-8") as fh:
            json.dump(base_data, fh, sort_keys=True, separators=(",", ":"))
        for date_key in self.data["timeline"]:
            with open(f"./data/{date_key}.json", "w", encoding="utf-8") as fh:
                json.dump(
                    self.data["timeline"][date_key],
                    fh,
                    sort_keys=True,
                    separators=(",", ":"),
                )

    def update(self):
        print("UPDATE DATA")

        self.create_tmp_dir()

        # read the kmz backup repository
        data_list = self.get_kmz_list()

        # generate a full date range list, starting from the earliest kmz date
        dates = self.generate_date_range_list(data_list)
        self.dates = dates

        # get local data files
        files = [f.stem for f in pathlib.Path("./data").iterdir() if f.is_file()]
        if "base" in files:
            files.remove("base")  # remove 'base' from list

        # create a diff to find all missing data
        s = set(files)
        diff = [x for x in dates if x not in s]
        print(diff)

        if len(diff) == 0:
            print("nothing to update")
            return
        # so we have missing data

        # add latest date to the diff list
        diff.append(dates[-1])
        print(diff)

        # load old base data
        with open("./data/base.json", encoding="utf-8") as fh:
            file_contents = fh.read()
            base_data = json.loads(file_contents)

        # init some data with the old base data
        self.base_date_key = base_data["date"]
        # self.data['fortifications'] = base_data['fortifications']
        # self.data['dragon_teeth'] = base_data['dragon_teeth']
        # self.data['styles'] = base_data['styles']
        self.data["unit_map"] = base_data["unit_map"]
        # keys are strings (from json) -> convert to int
        self.data["unit_map"] = {int(k): v for k, v in self.data["unit_map"].items()}
        # create unit check dict
        for k, v in self.data["unit_map"].items():
            self.unit_check[v["n"]] = k

        # based on the diff, prepare the wanted data
        # which is just a list of kmz to process
        wanted_data = []
        for x in data_list:
            if x["real_data_date"] in diff:
                wanted_data.append(x)

        # if we process newer data, than we already have,
        # set is_latest flag
        current_base_data_date = base_data["date"]
        new_latest_date = None
        for wd in wanted_data:
            if current_base_data_date <= wd["real_data_date"]:
                new_latest_date = wd["real_data_date"]
        if new_latest_date is not None:
            print("update latest flag")
            for wd in wanted_data:
                if new_latest_date == wd["real_data_date"]:
                    wd["is_latest"] = True

        print(wanted_data)

        # init data (will be filled later on)
        self.init_data(diff)

        # threadpool to process the data
        with ThreadPoolExecutor(max_workers=5) as executor:
            thread = executor.map(self.process_kmz, wanted_data)
            for result in thread:
                date_key = result["date_key"]
                self.data["timeline"][date_key]["unit_count"] = result["unit_count"]
                self.data["timeline"][date_key]["units"] = result["units"]
                self.data["timeline"][date_key]["frontline"] = result["frontline"]

        # update sidc
        self.data["unit_map"] = sidc.update(self.data["unit_map"])

        # finally, save the data to <date>.json & base.json
        self.save_data()

    def generate(self):

        self.create_tmp_dir()

        # read the kmz backup repository
        data_list = self.get_kmz_list()
        # flag latest item (from which we extract the base data, like frontline ect.)
        data_list[-1]["is_latest"] = True

        # generate a full date range list, starting from the earliest kmz date
        dates = self.generate_date_range_list(data_list)
        self.dates = dates

        # init data (will be filled later on)
        self.init_data(dates)

        # define what data we want to process
        wanted_data = data_list
        # wanted_data = data_list[-2:]

        # threadpool to process the data
        with ThreadPoolExecutor(max_workers=5) as executor:
            thread = executor.map(self.process_kmz, wanted_data)
            for result in thread:
                date_key = result["date_key"]
                self.data["timeline"][date_key]["unit_count"] = result["unit_count"]
                self.data["timeline"][date_key]["units"] = result["units"]
                self.data["timeline"][date_key]["frontline"] = result["frontline"]

        # update sidc
        self.data["unit_map"] = sidc.update(self.data["unit_map"])

        # finally, save the data to <date>.json & base.json
        self.save_data()

    def check_sidc(self):
        data = {}
        try:
            with open("./data/base.json", "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as e:
            print("Invalid JSON syntax:", e)
        sidc.check(data["unit_map"])

    def force_sidc(self):
        data = {}
        try:
            with open("./data/base.json", "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as e:
            print("Invalid JSON syntax:", e)

        if "unit_map" in data:
            data["unit_map"] = sidc.update(data["unit_map"])
            # safe json file
            with open("./data/base.json", "w", encoding="utf-8") as fh:
                json.dump(data, fh, sort_keys=True, separators=(",", ":"))

    def create_tmp_dir(self):
        os.makedirs('./tmp', exist_ok=True)



if __name__ == "__main__":

    # args setup
    argParser = argparse.ArgumentParser()
    grp = argParser.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "-g", "--generate", action="store_true", help="generate data from scratch"
    )
    grp.add_argument("-u", "--update", action="store_true", help="update data")
    grp.add_argument("-s", "--sidc", action="store_true", help="check unit 2 sidc")
    grp.add_argument("-f", "--force", action="store_true", help="force sidc update")
    args = argParser.parse_args()

    # INIT MapData CLASS
    mapdata = MapData()

    # depending on the type of action we
    # now run generate or update
    if args.generate:
        mapdata.generate()
    elif args.update:
        mapdata.update()
    elif args.sidc:
        mapdata.check_sidc()
    elif args.force:
        mapdata.force_sidc()
