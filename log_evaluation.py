import json

WIN_MARKET = '1.170226122'


def frac_to_dec_odds(numerator, denominator):
    return numerator / denominator + 1.0


def get_forecast_odds(description):
    return {
        runner['selectionId']: frac_to_dec_odds(int(runner['metadata']['FORECASTPRICE_NUMERATOR']),
                                                int(runner['metadata']['FORECASTPRICE_DENOMINATOR']))
        for runner in description['runners']
    }


def parse_log(filename='assessment_log.json'):
    log = {}
    with open(filename) as json_file:
        data = [json.loads(line) for line in json_file]
        for line in data:
            app_data = line['app_data']
            if 'description' in app_data:
                market_id = app_data['marketId']
                if market_id not in log:
                    log[market_id] = {}
                log[market_id]['description'] = line
                log[market_id]['forecast'] = get_forecast_odds(app_data)
            elif 'status' in app_data and app_data['status'] == 'OPEN':
                market_id = app_data['marketId']
                if 'info' in log[market_id]:
                    log[market_id]['info'].append(line)
                else:
                    log[market_id]['info'] = [line]
        return log


def extract_orders_data(parsed_log):
    orders_data = {}
    previous_info = {}
    market_info = parsed_log[WIN_MARKET]
    for i, info_line in enumerate(market_info['info']):
        for runner_data in info_line['app_data']['runners']:
            runner_id = runner_data['selectionId']
            runner_bets = {order['betId']: order for order in (runner_data['orders'] or [])}

            new_orders = set(runner_bets.keys()).difference(
                previous_info[runner_id]['order_ids'] if runner_id in previous_info else set()
            )
            if len(new_orders) > 0:
                for new_order in new_orders:
                    if runner_id not in orders_data:
                        orders_data[runner_id] = {}
                    orders_data[runner_id][new_order] = {
                        'info': previous_info[runner_id],
                        'order': runner_bets[new_order],
                        'sequence_n': i
                    }

            runner_data['order_ids'] = set(runner_bets.keys())
            previous_info[runner_id] = runner_data

    return orders_data


def count_orders(orders_data):
    return sum(len(runner_orders) for runner_orders in orders_data.values())


def get_order_limits(orders_data):
    limits = {}
    for runner_id, runner_orders in orders_data.items():
        for order_info in runner_orders.values():
            if runner_id not in limits:
                limits[runner_id] = {
                    'min_back': -1,
                    'max_lay': -1
                }
            if order_info['order']['side'] == 'BACK':
                min_back = limits[runner_id]['min_back']
                if min_back == -1 or order_info['order']['price'] < min_back:
                    limits[runner_id]['min_back'] = order_info['order']['price']
            if order_info['order']['side'] == 'LAY':
                max_lay = limits[runner_id]['max_lay']
                if max_lay == -1 or order_info['order']['price'] > max_lay:
                    limits[runner_id]['max_lay'] = order_info['order']['price']
    return limits


def test_odds_better_than_forecasted(parsed_log, orders_data):
    test_results = {'back_holds': 0, 'back_fails': 0, 'lay_holds': 0, 'lay_fails': 0}
    for runner_id, runner_orders in orders_data.items():
        if runner_orders is not None:
            for order_info in runner_orders.values():
                if order_info['order']['side'] == 'BACK':
                    if order_info['order']['price'] < parsed_log[WIN_MARKET]['forecast'][runner_id]:
                        test_results['back_fails'] += 1
                    else:
                        test_results['back_holds'] += 1
                elif order_info['order']['side'] == 'LAY':
                    if order_info['order']['price'] > parsed_log[WIN_MARKET]['forecast'][runner_id]:
                        test_results['lay_fails'] += 1
                    else:
                        test_results['lay_holds'] += 1
    return test_results


def test_threshold_betting(parsed_log, order_limits):
    winners_market_runners_log = [winners_info['app_data']['runners'] for winners_info in
                                  parsed_log[WIN_MARKET]['info']]
    n_bets = 0
    for i, log_line in enumerate(winners_market_runners_log):
        for runner_data in log_line:
            runner_id = runner_data['selectionId']
            if runner_id not in order_limits:
                continue
            available_backs = [offer['price'] for offer in runner_data['ex']['availableToBack']]
            min_back_available = min(available_backs) if len(available_backs) > 0 else -1

            available_lays = [offer['price'] for offer in runner_data['ex']['availableToLay']]
            max_lay_available = max(available_lays) if len(available_lays) > 0 else -1

            min_back = order_limits[runner_id]['min_back']
            max_lay = order_limits[runner_id]['max_lay']
            if min_back_available != -1 and min_back_available >= min_back != -1:
                n_bets += 1
            if max_lay_available != -1 and max_lay_available <= max_lay != -1:
                n_bets += 1
    return n_bets


def test_odds_better_than_previous(orders_data):
    test_results = {'back_holds': 0, 'back_fails': 0, 'lay_holds': 0, 'lay_fails': 0}
    for runner_id, runner_orders in orders_data.items():
        for order_id, order_data in runner_orders.items():
            last_price = order_data['info']['lastPriceTraded']
            order = order_data['order']
            price = order["price"]
            side = order["side"]
            if side == 'BACK':
                if last_price > price:
                    test_results['back_fails'] += 1
                else:
                    test_results['back_holds'] += 1
            elif side == 'LAY':
                if last_price < price:
                    test_results['lay_fails'] += 1
                else:
                    test_results['lay_holds'] += 1

    return test_results


def get_profit(parsed_log, winning_id=27157433):
    win_market_final_runners = parsed_log[WIN_MARKET]['info'][-1]['app_data']['runners']
    runner_orders = {runner['selectionId']: runner['orders'] for runner in win_market_final_runners}
    profit, staked = 0, 0
    for runner_id, orders in runner_orders.items():
        if orders is not None:
            for order in orders:
                staked += order['sizeMatched']
                if order['side'] == 'BACK':
                    if runner_id == winning_id:
                        profit += order['sizeMatched'] * (order['avgPriceMatched'] - 1)
                    else:
                        profit -= order['sizeMatched']
                elif order['side'] == 'LAY':
                    if runner_id == winning_id:
                        profit -= order['sizeMatched'] * (order['avgPriceMatched'] - 1)
                    else:
                        profit += order['sizeMatched']
    return profit, staked


if __name__ == '__main__':
    log = parse_log()
    orders = extract_orders_data(log)
    limits = get_order_limits(orders)

    print(f'Threshold opportunities: {test_threshold_betting(log, limits)}')
    print(f'Bet count: {count_orders(orders)}')

    print(f'Test forecasted: {test_odds_better_than_forecasted(log, orders)}')
    print(f'Test lastprice: {test_odds_better_than_previous(orders)}')

    profit, staked = get_profit(log)
    print(f'Profit: £{int(profit)}, Staked: {int(staked)}')
