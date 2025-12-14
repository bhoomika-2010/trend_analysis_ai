from database.db import create_tables

if __name__ == '__main__':
    print('Creating DB schema (topics, entities, influencers, aggregates, geo_metrics)...')
    ok = create_tables()
    if ok:
        print('Schema creation completed.')
    else:
        print('Schema creation failed. See errors above.')
