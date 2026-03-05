from db.session import SessionLocal
from models.user import User

with SessionLocal() as db:
    users = db.query(User).all()
    for user in users:
        pwd = user.hashed_password
        is_plaintext = pwd in ["test123", "admin123"]
        print(f'{user.email}:')
        print(f'  Password Hash: {pwd[:40]}...')
        print(f'  Is plaintext: {is_plaintext}')
        if not is_plaintext and '$' in pwd:
            salt, hash_part = pwd.split('$')
            print(f'  Salt length: {len(salt)}, Hash length: {len(hash_part)}')
            print(f'  Status: ENCRYPTED')
        print()
