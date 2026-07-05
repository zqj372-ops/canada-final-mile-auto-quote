This is a JSON list of Canadian postal codes and the preferred city name for each.

Extracted from the Statistics Canada National Address Register published July 2025.
This means the list should contain every Canadian postal code that actually had at least one street address in it as of July.

Here is a function that returns the province abbreviation using the first 3 characters of a postal code.
This saves storage space by not having it in every line of the JSON file.

```js
function getCanadaProvinceFromPostalCode(postalcode) {
    switch (postalcode.toUpperCase().substring(0, 1)) {
        case "A":
            return "NL";
        case "B":
            return "NS";
        case "C":
            return "PE";
        case "E":
            return "NB";
        case "G":
        case "H":
        case "J":
            return "QC";
        case "K":
        case "L":
        case "M":
        case "N":
        case "P":
            return "ON";
        case "R":
            return "MB";
        case "S":
            return "SK";
        case "T":
            return "AB";
        case "V":
            return "BC";
        case "X":
            // Northwest Territories and Nunavut are both X, look at more chars
            switch (postalcode.toUpperCase().substring(0, 3)) {
                case "X1A":
                case "X0E":
                case "X0G":
                    return "NT";
                case "X0A":
                case "X0B":
                case "X0C":
                    return "NU";
            }
            return "";
        case "Y":
            return "YT";
        default:
            return "";
    }
}
```
