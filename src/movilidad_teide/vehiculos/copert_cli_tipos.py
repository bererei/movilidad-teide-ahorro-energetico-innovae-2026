"""vehiculos: copert cli tipos. Conservo los criterios y las operaciones del estudio."""
from __future__ import annotations


VEHICLE = ('Buses', 'Diesel', 'Urban Buses Standard 15 - 18 t', 'Euro VI D/E')

REQUIRED_SHEETS = (
    'STOCK', 'RURAL_SHARE',
    'RURAL_LOAD', 'RURAL_ROAD_SLOPE', 'FB~FUEL_BALANCE',
)

INHERITABLE_SHEETS = ('MEAN_ACTIVITY', 'RURAL_SPEED')

REFERENCE_UNITS = {
    'STOCK': '[n]', 'MEAN_ACTIVITY': '[km]', 'RURAL_SPEED': '[km/h]',
    'URBAN_PEAK_SPEED': '[km/h]', 'URBAN_OFF_PEAK_SPEED': '[km/h]',
    'HIGHWAY_SPEED': '[km/h]', 'LIFETIME_CUMUL_ACTIVITY': '[km]',
    'RURAL_LOAD': '[%]', 'RURAL_ROAD_SLOPE': '[%]', 'RURAL_SHARE': '[%]',
    'URBAN_PEAK_SHARE': '[%]', 'URBAN_OFF_PEAK_SHARE': '[%]', 'HIGHWAY_SHARE': '[%]',
    'FB~FUEL_BALANCE': '[1/0]',
}

CAR_MODES = {'urban_peak':'PK','urban_off_peak':'OP','rural':'R','highway':'H'}

CAR_INPUT_PREFIX = {'urban_peak':'URBAN_PEAK','urban_off_peak':'URBAN_OFF_PEAK',
                    'rural':'RURAL','highway':'HIGHWAY'}

CAR_BIFUEL_PAIRS = {
    'LPG Bifuel': ('LPG','Petrol'), 'CNG Bifuel': ('CNG','Petrol'),
    'Petrol PHEV': ('Petrol','Electricity'), 'Diesel PHEV': ('Diesel','Electricity'),
}
