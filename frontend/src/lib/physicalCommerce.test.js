import { cartKey, availableFor, priceFor, shippingAddressValid } from './physicalCommerce';
const product = {fulfillment_type:'physical',price_idr:10000,variants:[{_id:'a',available:1,price_override:0},{_id:'b',available:0,price_override:null}]};
test('two variants preserve separate cart identities and stock bounds',()=>{
  expect(cartKey({pid:'p',variant_id:'a'})).not.toBe(cartKey({pid:'p',variant_id:'b'}));
  expect(availableFor(product,{variant_id:'a'})).toBe(1);
  expect(availableFor(product,{variant_id:'b'})).toBe(0);
  expect(availableFor(product,{variant_id:'missing'})).toBe(0);
});
test('zero override is a valid price and null falls back to product price',()=>{
  expect(priceFor(product,{variant_id:'a'})).toBe(0);
  expect(priceFor(product,{variant_id:'b'})).toBe(10000);
});
test('address validation requires six fields and Indonesian postal code',()=>{
  const address={recipient_name:'Buyer',phone:'08123456789',address_line_1:'Road',city:'Bandung',province:'Jawa Barat',postal_code:'40111',country:'ID'};
  expect(shippingAddressValid(address)).toBe(true);
  expect(shippingAddressValid({...address,city:''})).toBe(false);
  expect(shippingAddressValid({...address,postal_code:'1234'})).toBe(false);
});
