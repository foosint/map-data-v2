# UA Control Map Data Collect

## Prerequisites

- Python 12.x

## Install (local)

`pip install -r requirements.txt`

## Run (local)

Load & write all geos from the worksheet
<br>
`python geos.py`

Initial loading of all daily frontline & unit data from the backup .kmz
<br>
`python layer.py --generate`

Update daily frontline & unit data
<br>
`python layer.py --update`