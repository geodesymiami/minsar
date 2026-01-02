import os
import pandas as pd

scratch = os.getenv('SCRATCHDIR')

def main(file_name):
    path = os.path.join(scratch, file_name) if not(os.path.isabs(file_name)) else file_name

    if not os.path.exists(path):
        raise FileNotFoundError(f"File {file_name} does not exist in {scratch}")

    df = pd.read_excel(path)

    return df


if __name__ == '__main__':
    main()