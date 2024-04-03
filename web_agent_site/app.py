import argparse, json, logging, random
import redis
import time
from pathlib import Path
from ast import literal_eval

from flask import (
    Flask,
    request,
    redirect,
    url_for
)

from rich import print

from web_agent_site.engine.engine import (
    load_products,
    init_search_engine,
    convert_web_app_string_to_var,
    get_top_n_product_from_keywords,
    get_product_per_page,
    map_action_to_html,
    END_BUTTON
)
from web_agent_site.engine.goal import get_reward, get_goals
from web_agent_site.utils import (
    generate_mturk_code,
    setup_logger,
    DEFAULT_FILE_PATH,
    DEBUG_PROD_SIZE,
)

app = Flask(__name__)

search_engine = None
all_products = None
product_item_dict = None
product_prices = None
attribute_to_asins = None
goals = None
weights = None

# user_sessions = dict()
user_log_dir = None
SHOW_ATTRS_TAB = False

import redis
conn = redis.Redis(host='localhost', port=6380, db=0)

def exists_session_id(session_id):
    return conn.get(session_id) is not None

def set_user_session(session_id, value:dict ):
    conn.set(session_id, json.dumps(value))

def get_user_session(session_id):
    return json.loads(conn.get(session_id))
    

@app.route('/')
def home():
    return redirect(url_for('index', session_id="abc"))

@app.route('/<session_id>', methods=['GET', 'POST'])
def index(session_id):
    # print(f"Resetting with Session ID: {session_id}")
    start = time.time()
    global user_log_dir
    global all_products, product_item_dict, \
           product_prices, attribute_to_asins, \
           search_engine, \
           goals, weights 

    if search_engine is None:
        print("Loading products and initializing search engine")
        all_products, product_item_dict, product_prices, attribute_to_asins = \
            load_products(
                filepath=DEFAULT_FILE_PATH,
                num_products=DEBUG_PROD_SIZE
            )
        search_engine = init_search_engine(num_products=DEBUG_PROD_SIZE)
        goals = get_goals(all_products, product_prices)
        print(f"Loaded {len(goals)} goals")
        random.seed(233)
        random.shuffle(goals)
        weights = [goal['weight'] for goal in goals]

    if not exists_session_id(session_id) and 'fixed' in session_id:
        goal_dix = int(session_id.split('_')[-1])
        goal = goals[goal_dix] % len(goals)
        instruction_text = goal['instruction_text']
        set_user_session(session_id, {'goal': goal, 'done': False})
        if user_log_dir is not None:
            setup_logger(session_id, user_log_dir)
    elif not exists_session_id(session_id):
        goal = random.choices(goals, weights)[0]
        instruction_text = goal['instruction_text']
        set_user_session(session_id, {'goal': goal, 'done': False})
        if user_log_dir is not None:
            setup_logger(session_id, user_log_dir)
    else:
        instruction_text = get_user_session(session_id)['goal']['instruction_text']

    if request.method == 'POST' and 'search_query' in request.form:
        keywords = request.form['search_query'].lower().split(' ')
        return redirect(url_for(
            'search_results',
            session_id=session_id,
            keywords=keywords,
            page=1,
        ))
    if user_log_dir is not None:
        logger = logging.getLogger(session_id)
        logger.info(json.dumps(dict(
            page='index',
            url=request.url,
            goal=get_user_session(session_id)['goal'],
        )))

    end = time.time()
    # print(f"Done resetting with Session ID: {session_id} in {end-start:.2f}s")
    return map_action_to_html(
        'start',
        session_id=session_id,
        instruction_text=instruction_text,
    )


@app.route(
    '/search_results/<session_id>/<keywords>/<page>',
    methods=['GET', 'POST']
)
def search_results(session_id, keywords, page):
    # print(f"Search Results for Session ID: {session_id}")
    start = time.time()
    instruction_text = get_user_session(session_id)['goal']['instruction_text']
    page = convert_web_app_string_to_var('page', page)
    keywords = convert_web_app_string_to_var('keywords', keywords)
    top_n_products = get_top_n_product_from_keywords(
        keywords,
        search_engine,
        all_products,
        product_item_dict,
        attribute_to_asins,
    )
    products = get_product_per_page(top_n_products, page)
    html = map_action_to_html(
        'search',
        session_id=session_id,
        products=products,
        keywords=keywords,
        page=page,
        total=len(top_n_products),
        instruction_text=instruction_text,
    )
    logger = logging.getLogger(session_id)
    logger.info(json.dumps(dict(
        page='search_results',
        url=request.url,
        goal=get_user_session(session_id)['goal'],
        content=dict(
            keywords=keywords,
            search_result_asins=[p['asin'] for p in products],
            page=page,
        )
    )))
    end = time.time()
    # print(f"Done Search Results for Session ID: {session_id} in {end-start:.2f}s")
    return html


@app.route(
    '/item_page/<session_id>/<asin>/<keywords>/<page>/<options>',
    methods=['GET', 'POST']
)
def item_page(session_id, asin, keywords, page, options):
    # print(f"Item Page for Session ID: {session_id}")
    start = time.time()
    options = literal_eval(options)
    product_info = product_item_dict[asin]

    goal_instruction = get_user_session(session_id)['goal']['instruction_text']
    product_info['goal_instruction'] = goal_instruction

    html = map_action_to_html(
        'click',
        session_id=session_id,
        product_info=product_info,
        keywords=keywords,
        page=page,
        asin=asin,
        options=options,
        instruction_text=goal_instruction,
        show_attrs=SHOW_ATTRS_TAB,
    )
    logger = logging.getLogger(session_id)
    logger.info(json.dumps(dict(
        page='item_page',
        url=request.url,
        goal=get_user_session(session_id)['goal'],
        content=dict(
            keywords=keywords,
            page=page,
            asin=asin,
            options=options,
        )
    )))
    end = time.time()
    # print(f"Done Item Page for Session ID: {session_id} in {end-start:.2f}s")
    return html


@app.route(
    '/item_sub_page/<session_id>/<asin>/<keywords>/<page>/<sub_page>/<options>',
    methods=['GET', 'POST']
)
def item_sub_page(session_id, asin, keywords, page, sub_page, options):
    # print(f"Item Sub Page for Session ID: {session_id}")
    start = time.time()
    options = literal_eval(options)
    product_info = product_item_dict[asin]

    goal_instruction = get_user_session(session_id)['goal']['instruction_text']
    product_info['goal_instruction'] = goal_instruction

    html = map_action_to_html(
        f'click[{sub_page}]',
        session_id=session_id,
        product_info=product_info,
        keywords=keywords,
        page=page,
        asin=asin,
        options=options,
        instruction_text=goal_instruction
    )
    logger = logging.getLogger(session_id)
    logger.info(json.dumps(dict(
        page='item_sub_page',
        url=request.url,
        goal=get_user_session(session_id)['goal'],
        content=dict(
            keywords=keywords,
            page=page,
            asin=asin,
            options=options,
        )
    )))
    end = time.time()
    # print(f"Done Item Sub Page for Session ID: {session_id} in {end-start:.2f}s")
    return html


@app.route('/done/<session_id>/<asin>/<options>', methods=['GET', 'POST'])
def done(session_id, asin, options):
    # print(f"Done for Session ID: {session_id}")
    start = time.time()
    options = literal_eval(options)
    goal = get_user_session(session_id)['goal']
    purchased_product = product_item_dict[asin]
    price = product_prices[asin]

    reward, reward_info = get_reward(
        purchased_product,
        goal,
        price=price,
        options=options,
        verbose=True
    )
    new_user_session = get_user_session(session_id)
    new_user_session['done'] = True
    new_user_session['reward'] = reward
    set_user_session(session_id, new_user_session)
    # print(user_sessions)

    logger = logging.getLogger(session_id)
    logger.info(json.dumps(dict(
        page='done',
        url=request.url,
        goal=goal,
        content=dict(
            asin=asin,
            options=options,
            price=price,
        ),
        reward=reward,
        reward_info=reward_info,
    )))
    del logging.root.manager.loggerDict[session_id]
    
    end = time.time()
    # print(f"Done Done for Session ID: {session_id} in {end-start:.2f}s")
    return map_action_to_html(
        f'click[{END_BUTTON}]',
        session_id=session_id,
        reward=reward,
        asin=asin,
        options=options,
        reward_info=reward_info,
        query=purchased_product['query'],
        category=purchased_product['category'],
        product_category=purchased_product['product_category'],
        goal_attrs=get_user_session(session_id)['goal']['attributes'],
        purchased_attrs=purchased_product['Attributes'],
        goal=goal,
        mturk_code=generate_mturk_code(session_id),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebShop flask app backend configuration")
    parser.add_argument("--log", action='store_true', help="Log actions on WebShop in trajectory file")
    parser.add_argument("--attrs", action='store_true', help="Show attributes tab in item page")

    args = parser.parse_args()
    if args.log:
        user_log_dir = Path('user_session_logs/mturk')
        user_log_dir.mkdir(parents=True, exist_ok=True)
    SHOW_ATTRS_TAB = args.attrs

    app.run(host='0.0.0.0', port=3000)
