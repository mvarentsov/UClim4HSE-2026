import pandas as pd
import numpy as np
import glob
import os
import requests

from calendar import monthrange
from dateutil.rrule import *
from datetime import date, datetime, timedelta
from tqdm import tqdm

column_names = ['Время', 'Дата', 'Направление ветра', 'Скорость ветра', 'Видим.', 'Явления', 'Облачность', 'Т(С)', 'Тd(С)',
             'f(%)', 'Тe(С)', 'Тes(С)', 'Комфортность', 'P(гПа)', 'Po(гПа)', 'Тmin(С)', 'Tmax(С)', 'R(мм)', 'R24(мм)',
             'S(см)']

def url_exists(url):
    """
    Checks if a URL exists and is reachable.
    """
    try:
        # Use a HEAD request to avoid downloading the full body
        response = requests.head(url, timeout=5)
        # Check if status code is in the 2xx range (success)
        return 200 <= response.status_code < 300
    except requests.exceptions.ConnectionError:
        # Handles DNS failures, refused connections, etc
        return False
    except requests.exceptions.Timeout:
        # Handles request timeouts
        return False
    except requests.exceptions.RequestException as e:
        # Handles other potential exceptions
        print(f"An error occurred: {e}")
        return False

def load_weaclim4month (station_id, year, month, url="http://www.pogodaiklimat.ru/weather.php?"):

    last_day = monthrange(year, month)[1]

    date_now = date.today()
    date_request = date(year, month, last_day)
    if (date_request > date_now):
        last_day = date_now.day

    url = "{}id={}&bday=1&fday={}&amonth={}&ayear={}&bot=2".format(url, station_id, last_day, month,year)
    
    if not url_exists(url):
        raise Exception(f"URL {url} does not exist")

    try:
        df0 = pd.read_html(url, skiprows=5, converters={0: str, 1:str})
    except Exception as err:
        raise Warning(f"Failed to process {url} with error '{err}'")
        
    if not df0:
        raise Exception(f"There isn't any tabular data to read at {url}")

    try:
        df0 = df0[0]
        df1 = pd.read_html(url, skiprows=5)[1]
        df = pd.concat([df0, df1], axis=1)
        df.columns = column_names
        
        try:
            df['Datetime'] = pd.to_datetime((str(year)) + '.' + df['Дата'] + '.' + df['Время'],
                                            format='%Y.%d.%m.%H')
        except ValueError:
            df['Datetime'] = pd.to_datetime((str(year)) + '.' + df['Дата'] + '.' + df['Время'],
                                            format='%Y.%d.%m.%H:%M')
        df.drop(['Дата', 'Время'], axis=1, inplace=True)
        df.set_index('Datetime', inplace=True)
    except Exception as err:
        raise Warning(f"Failed to process {url} with error '{err}'")

    return df

def load_weaclim4period (station_id, start, end, out_dir, url=None):
    if url is None: 
        url = "http://www.pogodaiklimat.ru/usaweather.php?" if isinstance (station_id, str) else "http://www.pogodaiklimat.ru/weather.php?" 

    os.makedirs(out_dir, exist_ok=True)
    station_dir = os.path.join(out_dir, f'{station_id}')
    os.makedirs(station_dir, exist_ok=True)
        
   
    for cur_date in (pbar := tqdm (list (rrule(MONTHLY, dtstart=start, until = end)), desc="Loading weaclim data for %s"%str(station_id))):
        
        pbar.set_postfix_str(f"Processing: {cur_date.strftime('%Y-%m')}")
        
        datestr = cur_date.strftime('%Y%m')

        file_path = os.path.join(station_dir, f'{station_id}_{datestr}.csv')
        
        if os.path.exists(file_path):
            mod_datetime = datetime.fromtimestamp(os.path.getmtime(file_path))
            valid_datetime = datetime(cur_date.year, cur_date.month, 1)
            if mod_datetime - valid_datetime > timedelta(days=31):
                continue
            
        df = load_weaclim4month (station_id, cur_date.year, cur_date.month, url=url)
        df.to_csv(file_path)

def read_weaclim_dir (path, return_raw = False):

    def process_wind_direction(windd_str):
        if not windd_str or pd.isna(windd_str):  
            return np.nan
            
        wind_direction_map = {
            'С': 0,
            'СВ': 45,
            'В': 90,
            'ЮВ': 135,
            'Ю': 180,
            'ЮЗ': 225,
            'З': 270,
            'СЗ': 315,
            'штиль': np.nan,
            'нст': np.nan
        }
    
        try:
            return wind_direction_map[windd_str]
        except KeyError:
            print(f"Warning: Unexpected wind direction value: {windd_str}")
            return np.nan

    def process_wind_speed (str):
        vel = np.nan
        gust = np.nan

        if isinstance(str, int) or isinstance(str, float):
            vel = str
            return vel, gust

        try:
            parts = str.split(' ')
        except:
            raise Exception("Something wrong with wind string: " + str)
        if len(parts) > 1:
            if '-' in parts[0]:
                parts2 = parts[0].split('-')
                try:
                    vel = (float(parts2[0]) + float(parts2[1]))/2
                except Exception as e:
                    vel = np.nan 
            else:
                vel = float(parts[0])
            gust = float(parts[1].replace('{', '').replace('}', ''))
        else:
            vel = float(parts[0].replace('{', '').replace('}', ''))

        return vel, gust

    def process_cloudiness (cl_str):
        if isinstance(cl_str, int) or isinstance(str, float):
            return cl_str

        cl_tot = np.nan
        cl_low = np.nan
        if 'н/о' in cl_str:
            return cl_tot, cl_low
        elif 'ясно' in cl_str or 'нет нижн обл' in cl_str:
            cl_tot = 0
            cl_low = 0
        elif any(x in cl_str for x in ['баллов', 'балла', 'балл']):
            cl_words = cl_str.split()
            cl_tot = float(cl_words[0])
            cl_low = cl_tot
        elif '/' in cl_str:
            cl_words = cl_str.split()
            cl_str3 = cl_words[0]
            cl_words2 = cl_str3.split('/')
            try:
                cl_tot_str = cl_words2[0]
                cl_low_str = cl_words2[1]
            except:
                raise Exception("Something wrong with cloudiness string: " + cl_str)
            try:
                if cl_tot_str != '?':
                    cl_tot = float(cl_tot_str)
                if cl_low_str != '?':
                    try:
                        cl_low = float(cl_low_str)
                    except:
                        cl_low = np.nan
            except:
                raise Exception("Something wrong with cloudiness string: " + cl_str)
        else:
            raise Exception("Something wrong with cloudiness string: " + cl_str)
        return cl_tot, cl_low

    all_files = glob.glob(os.path.join(path , "*.csv"))    

    li = []

    for filename in (pbar := tqdm(all_files)):
        pbar.set_postfix_str(f'reading {filename}')
        df = pd.read_csv(filename, header=0, parse_dates=['Datetime'], index_col = ['Datetime'])
        li.append(df)

    frame = pd.concat(li, axis=0) #, ignore_index=True)

    frame = frame.sort_index()

    frame_sel = frame[['Т(С)', 'f(%)', 'P(гПа)', 'Po(гПа)']].copy()
    frame_sel.columns = ['t2m', 'rh2m', 'slp', 'ps']

    
    frame_sel.loc[:, 'vel10m'], frame_sel.loc[:, 'gust10m'] = zip(*frame['Скорость ветра'].apply(process_wind_speed))
    frame_sel.loc[:, 'tcc'], frame_sel.loc[:, 'lcc'] = zip(*frame['Облачность'].apply(process_cloudiness))
    frame_sel.loc[:, 'dir10m'] = frame['Направление ветра'].apply(process_wind_direction)
    
    if return_raw:
        return frame_sel, frame
    else:
        return frame_sel