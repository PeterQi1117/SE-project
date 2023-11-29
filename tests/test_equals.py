import datetime
from dateutil.relativedelta import relativedelta


def testDateWeek():
    current_date = datetime.datetime.utcnow()
    offset = -1
    current_date += relativedelta(weeks=offset)

    start_of_week = current_date - datetime.timedelta(days=current_date.weekday())
    end_of_week = start_of_week + datetime.timedelta(days=5)

    hours_difference = (end_of_week - start_of_week).total_seconds() / 3600

    assert hours_difference == 120, f"Week duration should be 120 hours, but is {hours_difference} hours"


def testDateMonth():
    current_date = datetime.datetime.utcnow()
    offset = -1
    current_date += relativedelta(months=offset)

    start_of_month = current_date.replace(day=1)
    end_of_month = start_of_month + relativedelta(months=1) - datetime.timedelta(days=1)

    days_difference = (end_of_month - start_of_month).days + 1 
    
    assert 28 <= days_difference <= 31, f"Month duration should be between 28 and 31 days, but is {days_difference} days"
