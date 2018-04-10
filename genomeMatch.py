"""genomeMatch.py: compares two Genome Link data reports"""
import json
import re
import sys
import asyncio
import concurrent.futures
from functools import partial
import genomelink
import boto3
from botocore.exceptions import ClientError

__copyright__ = 'Copyright (C) 2018 Milton Huang'
__license__ = 'MIT'
__version__ = '0.2.0'

PRINT_LIMIT = 22

# --------------- attributes keys -----------------
DATA_KEY = 'genome data'
SPEECHOUTPUT_KEY = 'speechOutput'
REPROMPT_KEY = 'repromptText'
# --------------- slots names -----------------
NAME_SLOT = 'name'
NAME_SLOTA = 'nameA'
NAME_SLOTB = 'nameB'
# --------------- DynamoDB names -----------------
USERID = 'userId'   # table key
DATA = 'data'       # table record

# local version
# DYNAMODB = boto3.resource('dynamodb', region_name='us-east-1',
#                           endpoint_url='http://localhost:8000')
DYNAMODB = boto3.resource('dynamodb', region_name='us-east-1')
db_table = DYNAMODB.Table('genomeTable')

DATA_SCOPE = [('report:agreeableness report:anger report:conscientiousness '
               'report:depression report:extraversion report:gambling '
               'report:harm-avoidance report:neuroticism report:openness '
               'report:novelty-seeking report:reward-dependence')]
TRAIT_LIST = ['agreeableness', 'anger', 'conscientiousness',
              'depression', 'extraversion', 'gambling',
              'harm-avoidance', 'neuroticism', 'openness',
              'novelty-seeking', 'reward-dependence']

"""
 * When editing messages pay attention to punctuation.
 Use question marks or periods.
"""

languageSupport = {
    'en-US': {
        'translation': {
            'AND': "and ",
            'OR': "or ",
            'SKILL_NAME': "Genome match",
            'HELP_MESSAGE': "This skill compares the traits from two genomes "
                            "that you have access to on genome link. ",
            'HELP_REPROMPT': "Try again. ",
            'NAME_OPTION': ("You can give a name to a recently downloaded "
                            "data set by saying name the data, then "
                            "the name like Bob, or mom, or test "),
            'LIST_OPTION': ("You can have me say the list of names of the "
                            "data sets by saying who is on my list? "),
            'COMPARE_OPTION': ("You can have me compare two data sets by "
                               "saying compare, then the two names. "),
            'LOAD_OPTION': ("You can have me load a new data set by saying "
                            "load more data. "),
            'REPEAT_OPTION': ("Say repeat if you want me to repeat the "
                              "last thing I said. "),
            'LLC_REPROMPT': "Say load data, list names, or compare data.  ",
            'TRY_AGAIN_MESSAGE': "Try again. ",
            'STOP_MESSAGE': "Goodbye!",
            'WELCOME_MESSAGE': "Welcome to genome match. ",
            'NO_DATA_MESSAGE': "I have no records of previous data. ",
            'NO_DATA_REPROMPT': "I have no records of previous data. ",
            'GENOMELINK_MESSAGE': ("I am sending information to your "
                                   "alexa app so you can log into genome "
                                   "link with the user name and password for "
                                   "the data set you want me to download. "
                                   "Go there and click on link account. "
                                   "When you are done, say load data. "),
            'GENOMELINK_REPROMPT': ("I'm shutting off while you take "
                                    "care of the genome link authentication "
                                    "and permissions. Continue when you are "
                                    "ready by saying open genome match, "
                                    "then load data. "),
            'GENOMELOAD_MESSAGE': ("I am downloading the data from "
                                   "genome link. "),
            'GENOMELOAD_REPROMPT': ("I'm shutting off while the data "
                                    "downloads. Continue when you are "
                                    "ready by saying open genome match"),
            'GENOMELOAD_CONFIRM': "I have downloaded the data set. ",
            'GENOMELOAD_ERROR': ("I got an error while trying "
                                 "to download data. You can try again, "
                                 "or you can go back to the alexa app "
                                 "and try to link account again. "),
            'DATA_COUNT_MESSAGE': "You have {0} data sets you can compare. ",
            'MORE_DATA_MESSAGE': ("You need at least two data sets to be able "
                                  "to compare them. Please load a data set. "),
            'LIST_MESSAGE': "I currenly have data for ",
            'EMPTY_LIST_MESSAGE': "Your list of data sets is empty. ",
            'SELECT_MESSAGE': ("Please pick two names from the list to "
                               "compare them. "),
            'SELECT_REPROMPT': "Please pick two names. ",
            'NAMELESS_MESSAGE': "You have an nameless data set. ",
            'NO_NAMELESS_MESSAGE': "There are no nameless data sets to name. ",
            'NO_NAMED_MESSAGE': "There are no data sets named {0}. ",
            'GIVE_NAME_MESSAGE': ("What name would you like to give "
                                  "this data set? "),
            'NEW_NAME_MESSAGE': ("That name is already in use.  Please "
                                 "pick another one. "),
            'NAME_CONFIRM_MESSAGE': "I have named the data set {0}. ",
            'NO_MATCH_MESSAGE': ("There are no strong matches in genetic "
                                 "similarity for the traits I examined. "),
            'HIGH_MATCH_MESSAGE': "There was a strong match in {0} traits. ",
            'MOD_MATCH_MESSAGE': ("There was a moderately strong match "
                                  "in {0} traits. "),
            'MATCH_START_MESSAGE': "For {0} and {1}, ",
        },
    },
    "en-GB": {
        'translation': {
        },
    },
}

# --------------- entry point -----------------


def lambda_handler(event, context):
    """App entry point"""
    if event['request']['type'] == 'LaunchRequest':
        return on_launch(event['request'], event['session'])
    elif event['request']['type'] == 'IntentRequest':
        return on_intent(event['request'], event['session'])
    elif event['request']['type'] == 'SessionEndedRequest':
        return on_session_ended(event['session'])

# --------------- request handlers -----------------


def on_launch(request, session):
    """start"""
    userId = getuserId(session)
    dbdata = get_dbdata(db_table, userId)
    if 'attributes' in session:
        session['attributes'][DATA_KEY] = dbdata
    else:
        session['attributes'] = {}
    if dbdata is None:
        print("empty dbdata on launch")
        dbdata = {}
    else:
        print("on_launch dbdata: ", dbdata)
    locale = getlocale(request)
    resource = getresource(locale)
    speechmessage = resource['WELCOME_MESSAGE']
    (addmessage, speechreprompt,
     useLink) = get_options_messages(session, locale)
    speechmessage += addmessage
    session['attributes'][SPEECHOUTPUT_KEY] = speechmessage
    session['attributes'][REPROMPT_KEY] = speechreprompt
    if useLink:
        return response(session['attributes'],
                        response_ask_link_card(speechmessage, speechreprompt))
    else:
        return response(session['attributes'],
                        response_ask(speechmessage, speechreprompt))


def on_intent(request, session):
    """called on Intent"""
    intent_name = request['intent']['name']
    print("on_intent: " + intent_name)
    locale = getlocale(request)

    if intent_name == "LoadIntent":
        # check if have token or need to link
        if get_accessToken(session) == "":
            # return link_genome(session, locale)
            return link_sample(session, locale)
        else:
            if 'untitled' in session['attributes'][DATA_KEY]:
                # after listing, will ask for naming
                return get_list(session, locale)
            else:
                return download_genome(session, locale)
    elif intent_name == 'NameIntent':
        return set_name(request, session, locale)
    elif intent_name == 'ListIntent':
        return get_list(session, locale)
    elif intent_name == 'CompareIntent':
        return compare_data(request, session, locale)
    elif intent_name == 'AMAZON.RepeatIntent':
        return repeat_response(session)
    elif intent_name == 'AMAZON.CancelIntent':
        return stop_response(session, locale)
    elif intent_name == 'AMAZON.StopIntent':
        return stop_response(session, locale)
    elif intent_name == 'AMAZON.HelpIntent':
        return help_response(session, locale)
    return help_response(session, locale)


def link_genome(session, locale):
    """get oauth accessToken from genomeLink"""
    print("DEBUG: in link_genome with session: ", session)
    resource = getresource(locale)
    # check if nameless data before loading more
    session = check_init_session(session)
    if 'untitled' in session['attributes'][DATA_KEY]:
        speechmessage = (resource['NAMELESS_MESSAGE'] +
                         resource['GIVE_NAME_MESSAGE'])
        speechreprompt = resource['GIVE_NAME_MESSAGE']
        return response(session['attributes'],
                        response_ask(speechmessage, speechreprompt))
    speechmessage = resource['GENOMELINK_MESSAGE']
    speechreprompt = resource['GENOMELINK_REPROMPT']
    session['attributes'][SPEECHOUTPUT_KEY] = speechmessage
    session['attributes'][REPROMPT_KEY] = speechreprompt
    return response(session['attributes'],
                    response_ask_link_card(speechmessage, speechreprompt))


def link_sample(session, locale):
    """
    fake oauth accessToken from genomeLink using user name samples

    changes accessToken in session
    """
    print("DEBUG: in link_sample with session: ", session)
    resource = getresource(locale)
    # check if nameless data before loading more
    session = check_init_session(session)
    if 'untitled' in session['attributes'][DATA_KEY]:
        speechmessage = (resource['NAMELESS_MESSAGE'] +
                         resource['GIVE_NAME_MESSAGE'])
        speechreprompt = resource['GIVE_NAME_MESSAGE']
        return response(session['attributes'],
                        response_ask(speechmessage, speechreprompt))
    if 'testUser' not in session['attributes']:
        session['attributes']['testUser'] = 1
    # this doesn't work - can't set accessToken from skill
    # session['user']['accessToken'] = fetch_accessToken(session)
    print("DEBUG exit link_sample:", session)
    speechmessage = resource['GENOMELINK_MESSAGE']
    speechreprompt = resource['GENOMELINK_REPROMPT']
    session['attributes'][SPEECHOUTPUT_KEY] = speechmessage
    session['attributes'][REPROMPT_KEY] = speechreprompt
    return response(session['attributes'],
                    response_ask_link_card(speechmessage, speechreprompt))


def download_genome(session, locale):
    """use accessToken to download data from genomeLink"""
    err_flag = False
    err_names = []
    # TODO: add progressive response loading data
    # https://developer.amazon.com/docs/custom-skills/send-the-user-a-progressive-response.html

    loop = asyncio.get_event_loop()
    data_record = loop.run_until_complete(fetch_reports(session))
    resource = getresource(locale)
    if err_flag:
        print("error downloading genome for: ", err_names)
        speechmessage = resource['GENOMELOAD_ERROR']
        speechreprompt = resource['TRY_AGAIN_MESSAGE']
    else:
        print("downloaded genome data: ", data_record)
        session = check_init_session(session)
        session['attributes'][DATA_KEY]['untitled'] = data_record
        speechmessage = resource['GENOMELOAD_CONFIRM']
        speechmessage += resource['NAME_OPTION']
        speechreprompt = resource['NAME_OPTION']
    # clear token
    clearaccessToken(session)
    session['attributes'][SPEECHOUTPUT_KEY] = speechmessage
    session['attributes'][REPROMPT_KEY] = speechreprompt
    print("exit download_genome:", session)
    return response(session['attributes'],
                    response_ask(speechmessage, speechreprompt))


async def fetch_reports(session):
    """report fetching coroutine"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=11) as executor:
        loop = asyncio.get_event_loop()
        token = get_accessToken(session)
        futures = [
            loop.run_in_executor(
                executor,
                partial(genomelink.Report.fetch,
                        name=name, population='european', token=token)
            )
            for name in TRAIT_LIST
        ]
        data_record = {}
        for name, response in zip(TRAIT_LIST, await asyncio.gather(*futures)):
            data_record[name] = (response.summary['score'],
                                 clean_phrase(name, response.summary['text']))
            print('add record:', data_record[name])
        return data_record

        # try:
        #     trait = genomelink.Report.fetch(name=name, population='european',
        #                                     token=token)
        #     data_record[name] = (trait.summary['score'],
        #                          clean_phrase(name, trait.summary['text']))
        #     print('fetched:', data_record[name])
        # except:
        #     print('error in downloading:', name, sys.exc_info())
        #     err_flag = True
        #     err_names.append((name, sys.exc_info()[1],
        #                      sys.exc_info()[2].print_tb))


def set_name(request, session, locale):
    """get name for data set"""
    resource = getresource(locale)
    # check there is data to name
    session = check_init_session(session)
    if 'untitled' not in session['attributes'][DATA_KEY]:
        print("tried set_name with no data")
        speechmessage = resource['NO_NAMELESS_MESSAGE']
        (addmessage, speechreprompt,
         useLink) = get_options_messages(session, locale)
        speechmessage += addmessage
        session['attributes'][SPEECHOUTPUT_KEY] = speechmessage
        session['attributes'][REPROMPT_KEY] = speechreprompt
        if useLink:
            return response(session['attributes'],
                            response_ask_link_card(speechmessage,
                                                   speechreprompt))
        else:
            return response(session['attributes'],
                            response_ask(speechmessage, speechreprompt))

    slot_value = request['intent']['slots'][NAME_SLOT]['value']
    print("DEBUG: set_name slots: ", request['intent']['slots'])
    if slot_value in session['attributes'][DATA_KEY]:
        # name already used
        speechmessage = resource['NEW_NAME_MESSAGE']
        speechreprompt = resource['NEW_NAME_MESSAGE']
        print("DEBUG: name already in use: ", slot_value)
        session['attributes'][SPEECHOUTPUT_KEY] = speechmessage
        session['attributes'][REPROMPT_KEY] = speechreprompt
        return response(session['attributes'],
                        response_ask(speechmessage, speechreprompt))
    else:
        session['attributes'][DATA_KEY][slot_value] = (session['attributes']
                                                       [DATA_KEY]['untitled'])
        del session['attributes'][DATA_KEY]['untitled']
        speechmessage = resource['NAME_CONFIRM_MESSAGE'].format(slot_value)
        (addmessage, speechreprompt,
         useLink) = get_options_messages(session, locale)
        speechmessage += addmessage
        session['attributes'][SPEECHOUTPUT_KEY] = speechmessage
        session['attributes'][REPROMPT_KEY] = speechreprompt
        print("DEBUG: exit set_name: ", session, speechmessage)
        if useLink:
            return response(session['attributes'],
                            response_ask_link_card(speechmessage,
                                                   speechreprompt))
        else:
            return response(session['attributes'],
                            response_ask(speechmessage, speechreprompt))


def get_list(session, locale):
    """say list of names"""
    session = check_init_session(session)
    name_list = list(session['attributes'][DATA_KEY].keys())
    print("names in get_list: ", name_list)
    resource = getresource(locale)
    if len(name_list) == 0:
        speechmessage = resource['EMPTY_LIST_MESSAGE']
    else:
        speechmessage = resource['LIST_MESSAGE']
        speechmessage += say_list(name_list, locale)
    (addmessage, speechreprompt,
     useLink) = get_options_messages(session, locale)
    speechmessage += addmessage
    session['attributes'][SPEECHOUTPUT_KEY] = speechmessage
    session['attributes'][REPROMPT_KEY] = speechreprompt
    print("DEBUG: list response: ", speechmessage)
    if useLink:
        return response(session['attributes'],
                        response_ask_link_card(speechmessage, speechreprompt))
    else:
        return response(session['attributes'],
                        response_ask(speechmessage, speechreprompt))


def say_list(word_list, locale):
    """punctuate list for speaking"""
    resource = getresource(locale)
    output = ""
    for word in word_list[:-1]:
        output += word + ", "
    if len(word_list) > 1:
        output += resource['AND']
    output += word_list[-1] + ". "
    return output


def compare_data(request, session, locale):
    """compare genome reports of names in two slots"""
    # TODO: break up lists if longer than 5
    resource = getresource(locale)
    slotA_value = request['intent']['slots'][NAME_SLOTA]['value']
    slotB_value = request['intent']['slots'][NAME_SLOTB]['value']
    print("compare_data slots: ", request['intent']['slots'])
    session = check_init_session(session)
    data = session['attributes'][DATA_KEY]
    if len(data) < 2:
        speechmessage = resource['MORE_DATA_MESSAGE']
        speechreprompt = resource['LOAD_OPTION']
        session['attributes'][SPEECHOUTPUT_KEY] = speechmessage
        session['attributes'][REPROMPT_KEY] = speechreprompt
        return response(session['attributes'],
                        response_ask(speechmessage, speechreprompt))
    if slotA_value not in data or slotB_value not in data:
        # name not used in data
        if slotA_value not in data:
            badname = slotA_value
        else:
            badname = slotB_value
        speechmessage = resource['NO_NAMED_MESSAGE'].format(badname)
        speechmessage += resource['SELECT_MESSAGE']
        speechreprompt = resource['SELECT_REPROMPT']
        session['attributes'][SPEECHOUTPUT_KEY] = speechmessage
        session['attributes'][REPROMPT_KEY] = speechreprompt
        return response(session['attributes'],
                        response_ask(speechmessage, speechreprompt))

    (high_trait, moderate_trait) = get_comparison(data, slotA_value,
                                                  slotB_value)
    print("compare high: ", high_trait)
    print("compare moderate: ", moderate_trait)
    if len(high_trait) == 0 and len(moderate_trait) == 0:
        speechmessage = resource['NO_MATCH_MESSAGE']
    elif len(high_trait) != 0:
        speechmessage = resource['MATCH_START_MESSAGE'].format(slotA_value,
                                                               slotB_value)
        speechmessage += resource['HIGH_MATCH_MESSAGE'].format(len(high_trait))
        speechmessage += say_list(high_trait, locale)
        if len(moderate_trait) != 0:
            speechmessage += (resource['MOD_MATCH_MESSAGE']
                              .format(len(moderate_trait)))
            speechmessage += say_list(moderate_trait, locale)
    else:
        if len(moderate_trait) != 0:
            speechmessage = resource['MATCH_START_MESSAGE'].format(slotA_value,
                                                                   slotB_value)

            speechmessage += (resource['MOD_MATCH_MESSAGE']
                              .format(len(moderate_trait)))
            speechmessage += say_list(moderate_trait, locale)
    # options to repeat, do another comparison, or add more data
    speechmessage += resource['REPEAT_OPTION']
    speechmessage += resource['LOAD_OPTION']
    speechmessage += resource['LIST_OPTION'] + resource['OR']
    speechmessage += resource['COMPARE_OPTION']
    speechreprompt = resource['LLC_REPROMPT']
    session['attributes'][SPEECHOUTPUT_KEY] = speechmessage
    session['attributes'][REPROMPT_KEY] = speechreprompt
    return response(session['attributes'],
                    response_ask(speechmessage, speechreprompt))


def get_comparison(data, slotA, slotB):
    """
    Compare data for two names

    Takes data for each name and makes it a high match if both are 0 or 4
    makes it a moderate match if one is 0 and other is 1 or both are 1

    Args:
        data: data as stored in DATA_KEY attribute
        slotA_name: name of data to compare, assumed to be valid
        slotB_name: name of data to compare, assumed to be valid

    Returns:
        tuple of list of high matching traits and of moderate matching traits
    """
    high_trait = []
    moderate_trait = []
    print("comparing", slotA, ", ", slotB, "with data: ", data)
    for trait in TRAIT_LIST:
        if (data[slotA][trait][0] == 0 and data[slotB][trait][0] == 0 or
                data[slotA][trait][0] == 4 and data[slotB][trait][0] == 4):
            high_trait.append(data[slotA][trait][1])
        elif (data[slotA][trait][0] < 2 and data[slotB][trait][0] < 2 or
                data[slotA][trait][0] > 2 and data[slotB][trait][0] > 2):
            moderate_trait.append(data[slotA][trait][1])
    return (high_trait, moderate_trait)


def check_init_session(session):
    if 'attributes' not in session:
        session['attributes'] = {}
    if DATA_KEY not in session['attributes']:
        session['attributes'][DATA_KEY] = {}
    return session


def get_options_messages(session, locale):
    """
    Add messages outlining current options.  Contains a lot of the logic
    might need to factor out logic for more flexibility

    Args:
        session: current session
        locale: current locale
        speechmessage: message stem function will add to

    Returns:
        tuple of (output message, reprompt message, need to use linkCard)
    """
    resource = getresource(locale)
    session = check_init_session(session)
    if session['attributes'][DATA_KEY] == {}:
        output = resource['NO_DATA_MESSAGE']
        output += resource['LOAD_OPTION']
        reprompt = resource['NO_DATA_REPROMPT']
        return (output, reprompt, False)
    else:
        dbdata = session['attributes'][DATA_KEY]
        # check if nameless present
        if 'untitled' in dbdata:
            output = resource['NAMELESS_MESSAGE']
            output += resource['GIVE_NAME_MESSAGE']
            reprompt = resource['GIVE_NAME_MESSAGE']
            return (output, reprompt, False)
        # give count
        output = resource['DATA_COUNT_MESSAGE'].format(len(dbdata))
        if len(dbdata) >= 2:
            output += resource['SELECT_MESSAGE']
            reprompt = resource['SELECT_REPROMPT']
            return (output, reprompt, False)
        else:
            output += resource['MORE_DATA_MESSAGE']
            output += resource['GENOMELINK_MESSAGE']
            reprompt = resource['GENOMELINK_REPROMPT']
            return (output, reprompt, True)


def stop_response(session, locale):
    """stop message response"""
    resource = getresource(locale)
    speechmessage = resource['STOP_MESSAGE']
    return response(session['attributes'], response_tell(speechmessage))


def repeat_response(session):
    """repeat last speechoutput"""
    speechmessage = session['attributes'][SPEECHOUTPUT_KEY]
    speechreprompt = session['attributes'][REPROMPT_KEY]
    return response(session['attributes'],
                    response_ask(speechmessage, speechreprompt))


def help_response(session, locale):
    """help response"""
    resource = getresource(locale)
    speechmessage = resource['HELP_MESSAGE']
    speechreprompt = resource['HELP_REPROMPT']
    return response(session['attributes'],
                    response_ask(speechmessage, speechreprompt))


def on_session_ended(session):
    """called on session end"""
    userId = getuserId(session)
    session = check_init_session(session)
    print("on_session_ended data: ", session['attributes'][DATA_KEY])
    put_dbdata(db_table, userId, session['attributes'][DATA_KEY])


# --------------- request helpers -----------------


def getresource(locale):
    """get language strings for `locale`"""
    return languageSupport[locale]['translation']


def getlocale(request):
    """get locale from request"""
    locale = request['locale']
    if locale == "":
        locale = 'en-US'
    print("locale: ", locale)
    return locale


def getuserId(session):
    """get userId from session"""
    userId = session['user']['userId']
    print("userId: ", userId)
    return userId


def clean_phrase(trait, phrase):
    """
    clean phrase

    takes phrase from GenomeLink report and converts to verb phrase for Alexa
    note that some traits included for the future
    no cleaning of 'Intermediate' values (2), since never used currently
    """
    if (trait == 'bmi' or trait == 'body-fat-mass' or trait == 'breast-size'
       or trait == 'mathematical-ability' or trait == 'hippocampal-volume'
       or trait == 'reading-and-spelling-ability'):
        phrase = 'tend to have a ' + phrase + trait.replace('-', ' ')
    if trait == 'openness':
        if phrase.find('not to be'):
            phrase = 'tend not to be open to experience. '
        else:
            phrase = 'tend to be open to experience. '
    phrase = re.sub(r', slightly$', '', phrase)
    phrase = re.sub(r'^Weak', 'have low', phrase)
    phrase = re.sub(r'^Does not show', 'have low', phrase)
    phrase = re.sub(r'^Somewhat prone', 'are somewhat prone', phrase)
    phrase = re.sub(r'^Not easily', 'are not easily', phrase)
    phrase = re.sub(r'^Easily', 'are easily', phrase)
    phrase = re.sub(r'^Stronger tendency', 'have a strong tendency', phrase)
    phrase = re.sub(r'^Slight tendency', 'have a tendency', phrase)
    phrase = re.sub(r'^Strong', 'have high', phrase)
    phrase = re.sub(r'^Does not show', 'Have low', phrase)
    return "They " + phrase


def get_accessToken(session):
    """get accessToken from session

    if you don't authenticate, never fires
    to make test work, return if `testUser` exists in `attributes`
    """
    if ('accessToken' in session['user'] and
       session['user']['accessToken'] != ''):
        accessToken = session['user']['accessToken']
        if 'testUser' in session['attributes']:
            del session['attributes']['testUser']
    else:
        accessToken = ""
        if 'testUser' in session['attributes']:
            accessToken = ('GENOMELINKTEST00' +
                           str(session['attributes']['testUser']))
    print("DEBUG in get_accessToken: ", accessToken[0:PRINT_LIMIT])
    return accessToken


def fetch_accessToken(session):
    """get accessToken from Internet

    don't know if this can work; using test tokens for now
    """
    accessToken = get_accessToken(session)
    # for demo/testing
    if 'testUser' in session['attributes']:
        accessToken = ('GENOMELINKTEST00' +
                       str(session['attributes']['testUser']))
    else:
        print("ERROR: tried to fetch_accessToken with no testUser attribute")
        # make a default
        accessToken = 'GENOMELINKTEST001'
    print("DEBUG in fetch_accessToken: ", accessToken[0:PRINT_LIMIT])
    return accessToken


def clearaccessToken(session):
    """clear accessToken in session"""
    # TODO: figure out if this works with a real token; does it have to be
    # cleared in `context`, too?  This must set up a new login
    session['user']['accessToken'] = ''
    # if testing, increment
    if 'testUser' in session['attributes']:
        if session['attributes']['testUser'] < 9:
            session['attributes']['testUser'] += 1
        print("DEBUG testing inc testUser:", session['attributes']['testUser'])
    return session


def getapiAccessToken(context):
    """get apiAccessToken from context"""
    if 'apiAccessToken' in context['System']:
        apiAccessToken = context['System']['apiAccessToken']
    else:
        apiAccessToken = ""
    print("apiAccessToken: ", apiAccessToken[0:PRINT_LIMIT])
    return apiAccessToken


def get_dbdata(table, id):
    """
    Fetch data for user.

    Args:
    table -- dynamodb table
    id -- userId to fetch
    """
    try:
        response = table.get_item(
            Key={
                'userId': id
            }
        )
    except ClientError as e:
        print(e.response['Error']['Message'])
        item = {}
    else:
        if 'Item' in response:
            item = response['Item']
            print("GetItem succeeded:", json.dumps(item, indent=4))
        else:
            item = {}
    return item


def put_dbdata(table, id, data):
    """
    Save data for user.

    Args:
    table -- dynamodb table
    id -- userId to save to

    Returns:
    response
    """
    try:
        response = table.put_item(
            Item={
                USERID: id,
                DATA: data
            }
        )
    except ClientError as e:
        print(e.response['Error']['Message'])
        return response
    else:
        print("PutItem succeeded:" + id[0:PRINT_LIMIT])
        return response


# --------------- speech response handlers -----------------
# build the json responses
# https://developer.amazon.com/public/solutions/alexa/alexa-skills-kit/docs/alexa-skills-kit-interface-reference
# response text cannot exceed 8000 characters
# response size cannot exceed 24 kilobytes


def response_tell(output):
    """create a simple json tell response"""
    return {
        'outputSpeech': {
            'type': 'SSML',
            'ssml': "<speak>" + output + "</speak>"
        },
        'shouldEndSession': True
    }


def response_ask(output, reprompt):
    """create a json ask response"""
    return {
        'outputSpeech': {
            'type': 'SSML',
            'ssml': "<speak>" + output + "</speak>"
        },
        'reprompt': {
            'outputSpeech': {
                'type': 'SSML',
                'ssml': "<speak>" + reprompt + "</speak>"
            }
        },
        'shouldEndSession': False
    }


def response_tell_link_card(output):
    """create a json standard card and speech response"""
    return {
        'card': {
            'type': 'LinkAccount',
        },
        'outputSpeech': {
            'type': 'SSML',
            'ssml': "<speak>" + output + "</speak>"
        },
        'shouldEndSession': True
    }


def response_ask_link_card(output, reprompt):
    """create a json standard card and speech response"""
    return {
        'card': {
            'type': 'LinkAccount',
        },
        'outputSpeech': {
            'type': 'SSML',
            'ssml': "<speak>" + output + "</speak>"
        },
        'reprompt': {
            'outputSpeech': {
                'type': 'SSML',
                'ssml': "<speak>" + reprompt + "</speak>"
            }
        },
        'shouldEndSession': False
    }


def response(attributes, speech_response):
    """create a simple json response
    uses one of the speech_responses from above
    """
    return {
        'version': '1.0',
        'sessionAttributes': attributes,
        'response': speech_response
    }
